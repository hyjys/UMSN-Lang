"""UMSN-IDE Web 의 파이썬 쪽. 브라우저의 Pyodide 안에서 돈다 (worker.js 가 불러 씀).

모든 함수는 JS 가 다루기 쉽게 문자열(JSON)이나 숫자를 돌려준다.
Pyodide 에 기대는 부분은 ``set_host`` 로 받은 객체뿐이라, 보통 파이썬에서도 테스트할 수 있다.
"""

import base64
import io
import json
import linecache
import os
import sys

import pyumsn
from pyumsn import launcher, vocab
from pyumsn.errors import UmsnError, UmsnSyntaxError
from pyumsn.sourceio import read_source, write_source
from pyumsn.translator import (check_umsn, highlight_spans, py_to_umsn, suggest_name,
                               transliterate, umsn_to_py, untransliterate)

WORK = "/home/pyodide/work"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
MAX_FILE_BYTES = 20 * 1024 * 1024

_host = None
_font_family = None


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


def init(work_dir=WORK, host=None):
    """작업 폴더를 정하고 (없으면 만들고) 호스트(JS 쪽 콜백 모음)를 등록한다."""
    global WORK, _host
    WORK = work_dir
    _host = host
    os.makedirs(WORK, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    return _dump({"version": pyumsn.__version__, "python": sys.version.split()[0]})


# ---------------------------------------------------------------------------
# 편집기 도우미 (언어 서비스)
# ---------------------------------------------------------------------------
def analyze(src):
    """구문 강조 조각과 한글 전용 검사 결과."""
    spans = highlight_spans(src)
    lines = src.splitlines()
    problems = []
    for lineno, col, length, msg in check_umsn(src):
        suggestion = None
        if lineno is not None and col is not None and 1 <= lineno <= len(lines):
            word = lines[lineno - 1][col:col + (length or 0)]
            if word and "'%s'" % word in msg:
                suggestion = suggest_name(word)
        problems.append([lineno, col, length or 1, msg, suggestion])
    return _dump({"spans": spans, "problems": problems})


def to_py(src, name="<엄슨>"):
    try:
        return _dump({"ok": True, "code": umsn_to_py(src, filename=name)})
    except UmsnSyntaxError as exc:
        return _dump({"ok": False, "error": exc.report()})
    except UmsnError as exc:
        return _dump({"ok": False, "error": "엄슨 오류! %s" % exc})


def to_umsn(src, keep_symbols=False, name="<파이썬>"):
    try:
        return _dump({"ok": True, "code": py_to_umsn(src, filename=name, keep_symbols=bool(keep_symbols))})
    except UmsnError as exc:
        return _dump({"ok": False, "error": "엄슨 오류! %s" % exc})
    except SyntaxError as exc:
        return _dump({"ok": False, "error": "파이썬 문법 오류 (%s줄): %s" % (exc.lineno, exc.msg)})


def words():
    """단어장: [분류, 엄슨, 파이썬] 목록."""
    return _dump([list(w) for w in vocab.all_words()])


def translit(name):
    name = name.strip()
    if name in vocab.PY2UMSN:
        return _dump({"ok": True, "result": vocab.PY2UMSN[name], "note": "사전 단어"})
    try:
        return _dump({"ok": True, "result": transliterate(name), "note": "음역"})
    except ValueError as exc:
        return _dump({"ok": False, "error": str(exc)})


def untranslit(word):
    word = word.strip()
    py = vocab.UMSN2PY.get(word) or vocab.UMSN2SYMBOL.get(word)
    if py:
        return _dump({"ok": True, "result": py, "note": "사전 단어"})
    py = untransliterate(word)
    if py:
        return _dump({"ok": True, "result": py, "note": "음역"})
    return _dump({"ok": False, "error": "'%s' 는 엄슨 단어나 음역이 아니슨" % word})


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def python_for_imports():
    """작업 폴더의 모든 .umsn 을 파이썬으로 바꿔 이어 붙인 것 (필요한 패키지 찾기용)."""
    parts = []
    for name in sorted(os.listdir(WORK)):
        if name.endswith(".umsn"):
            try:
                parts.append(umsn_to_py(read_source(os.path.join(WORK, name))))
            except (UmsnError, OSError):
                pass
    return "\n".join(parts)


def clear_workspace():
    """작업 폴더를 비운다 (IDE 의 파일 목록이 곧 작업 폴더가 되도록 실행마다 새로 채움)."""
    import shutil
    for name in os.listdir(WORK):
        path = os.path.join(WORK, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def snapshot():
    """작업 폴더 파일들의 (크기, 수정 시각)."""
    state = {}
    for root, _dirs, files in os.walk(WORK):
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            state[os.path.relpath(path, WORK)] = [st.st_size, st.st_mtime]
    return _dump(state)


def changed_files(before):
    """``snapshot()`` 뒤로 새로 생기거나 바뀐 파일 이름 목록."""
    before = json.loads(before)
    after = json.loads(snapshot())
    return _dump(sorted(name for name, st in after.items()
                        if before.get(name) != st and st[0] <= MAX_FILE_BYTES))


def _purge_workspace_modules():
    """지난 실행에서 불러온 작업 폴더 모듈을 잊어서 고친 .umsn 이 다시 불러와지게 한다."""
    prefix = os.path.join(WORK, "")
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None) or ""
        if path.startswith(prefix):
            del sys.modules[name]


def _exit_code(exc):
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    sys.stderr.write("%s\n" % (code,))
    return 1


def run_program(main, args="[]"):
    """작업 폴더의 ``main`` (.umsn) 을 실행하고 종료 코드를 돌려준다.

    ``pyumsn`` 명령과 같은 launcher 를 써서 오류 메시지·추적 기록이 데스크톱과 같다.
    """
    args = json.loads(args) if isinstance(args, str) else list(args)
    path = os.path.join(WORK, main)
    _purge_workspace_modules()
    launcher._MAPS.clear()
    linecache.clearcache()
    os.chdir(WORK)
    try:
        source = read_source(path)
        py = umsn_to_py(source, filename=main)
    except UmsnSyntaxError as exc:
        sys.stderr.write(exc.report() + "\n")
        return 1
    except (UmsnError, OSError) as exc:
        sys.stderr.write("엄슨 오류! %s\n" % exc)
        return 1
    tmp = os.path.join(os.path.dirname(WORK) or "/tmp", ".umsn_run.py")
    write_source(tmp, py)
    saved = sys.modules.get("__main__"), list(sys.path), list(sys.argv)
    if "matplotlib" in sys.modules:
        _reset_matplotlib()
    try:
        return launcher.main([tmp, path] + [str(a) for a in args])
    except SystemExit as exc:
        return _exit_code(exc)
    except KeyboardInterrupt:
        sys.stderr.write("\n엄슨 중단!\n")
        return 130
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        main_module, sys.path[:], sys.argv[:] = saved
        if main_module is not None:
            sys.modules["__main__"] = main_module
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# matplotlib: 그림을 화면 대신 IDE 콘솔로
# ---------------------------------------------------------------------------
def setup_matplotlib(font_path=None):
    """Agg 백엔드 + 한글 글꼴(D2Coding) + plt.show → 콘솔에 그림."""
    global _font_family
    import warnings
    import matplotlib
    # Pyodide 의 Agg 가 내는 경고 (사용자 코드와 상관없음)
    warnings.filterwarnings("ignore", message=r"The [xy] parameter as float was deprecated")
    matplotlib.use("Agg")
    if font_path and os.path.exists(font_path):
        from matplotlib import font_manager
        font_manager.fontManager.addfont(font_path)
        _font_family = font_manager.FontProperties(fname=font_path).get_name()
    import matplotlib.pyplot as plt
    plt.show = _show_figures
    _reset_matplotlib()


def _reset_matplotlib():
    import matplotlib
    matplotlib.rcdefaults()
    matplotlib.use("Agg")
    if _font_family:
        matplotlib.rcParams["font.family"] = [_font_family, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
    if "matplotlib.pyplot" in sys.modules:
        sys.modules["matplotlib.pyplot"].close("all")


def _show_figures(*args, **kwargs):
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return
    for num in plt.get_fignums():
        fig = plt.figure(num)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        post_image("그림 %d" % num, buf.getvalue())
    plt.close("all")


def post_image(title, data):
    if _host is not None:
        _host.postImage(title, base64.b64encode(data).decode("ascii"))
