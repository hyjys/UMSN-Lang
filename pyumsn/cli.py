"""``pyumsn`` 명령줄 도구.

유닉스(POSIX/GNU) 관례를 따른다.

- 짧은 옵션은 ``-t``, 묶어 쓰기 ``-tq``, 값은 ``-o 파일`` 또는 ``-o파일``.
- 긴 옵션은 ``--output=파일`` 또는 ``--output 파일``, 헷갈리지 않으면 줄여 써도 된다 (``--out``).
- ``--`` 뒤는 모두 피연산자, ``-`` 는 표준 입력/출력.
- 실행할 때는 첫 피연산자(파일)에서 옵션 읽기를 멈춘다: 그 뒤는 모두 프로그램 인자 (``python`` 과 같음).
  변환·검사처럼 파일을 여러 개 받는 모드에서는 옵션과 파일을 섞어 써도 된다 (GNU 방식).
- 종료 상태: 0 성공, 1 오류, 2 잘못된 사용법. 실행할 때는 프로그램의 종료 상태.
"""

import fnmatch
import getopt
import os
import re
import shutil
import sys
from pathlib import Path

from . import __version__, vocab
from .errors import UmsnEncodingError, UmsnError, UmsnSyntaxError
from .sourceio import decode_source, read_source, write_source
from .translator import check_umsn, py_to_umsn, transliterate, umsn_to_py, untransliterate

PROG = "pyumsn"
IDE_PATH = Path(__file__).resolve().parent / "ide" / "umsn_ide.umsn"
STDIN_NAME = "<stdin>"

SHORT_OPTS = "hVc:kpietunwMo:x:aq"
LONG_OPTS = ["help", "version", "command=", "keep", "show-py", "interactive", "ide", "edit",
             "to-py", "to-umsn", "check", "words", "markdown", "translit", "untranslit",
             "output=", "exclude=", "no-copy", "ascii-symbols", "keep-symbols", "quiet"]

# 옵션 → (모드, 설정 이름)
_MODE_OPTS = {
    "-c": "command", "--command": "command",
    "-i": "repl", "--interactive": "repl",
    "-e": "ide", "--ide": "ide", "--edit": "ide",
    "-t": "topy", "--to-py": "topy",
    "-u": "toumsn", "--to-umsn": "toumsn",
    "-n": "check", "--check": "check",
    "-w": "words", "--words": "words",
    "--translit": "translit",
    "--untranslit": "untranslit",
}
_FLAG_OPTS = {
    "-k": "keep", "--keep": "keep",
    "-p": "show_py", "--show-py": "show_py",
    "-a": "keep_symbols", "--ascii-symbols": "keep_symbols", "--keep-symbols": "keep_symbols",
    "-q": "quiet", "--quiet": "quiet",
    "-M": "markdown", "--markdown": "markdown",
    "--no-copy": "no_copy",
}
_MODE_LABEL = {
    "command": "-c", "repl": "-i", "ide": "-e", "topy": "-t", "toumsn": "-u", "check": "-n",
    "words": "-w", "translit": "--translit", "untranslit": "--untranslit",
}
# 옵션 → 함께 쓸 수 있는 모드
_FLAG_MODES = {
    "keep": ("run", "command"), "show_py": ("run", "command"),
    "keep_symbols": ("toumsn",), "output": ("topy", "toumsn"),
    "quiet": ("topy", "toumsn", "check"), "markdown": ("words",),
    "exclude": ("topy", "toumsn", "check"), "no_copy": ("topy", "toumsn"),
}
_FLAG_LABEL = {"keep": "-k", "show_py": "-p", "keep_symbols": "-a", "output": "-o",
               "quiet": "-q", "markdown": "-M", "exclude": "-x", "no_copy": "--no-copy"}
# 파일을 여러 개 받는 모드: 옵션과 피연산자를 섞어 써도 된다
_PERMUTE_MODES = ("topy", "toumsn", "check", "ide", "words", "translit", "untranslit")
# 예전(1.x) 하위 명령 → 새 옵션
_OLD_COMMANDS = {"run": "pyumsn 파일.umsn", "topy": "pyumsn -t", "toumsn": "pyumsn -u",
                 "check": "pyumsn -n", "ide": "pyumsn -e", "repl": "pyumsn -i",
                 "words": "pyumsn -w"}

# 폴더(프로젝트)를 변환·검사할 때 들어가지 않는 폴더: 버전 관리, 캐시, 가상 환경, 빌드 부산물.
# pyvenv.cfg 나 conda-meta 가 든 폴더(가상 환경)도 건너뛴다.
SKIP_DIRS = frozenset([".git", ".hg", ".svn", ".bzr", "__pycache__", ".venv", ".tox", ".nox",
                       ".mypy_cache", ".pytest_cache", ".ruff_cache", ".eggs", "node_modules",
                       "site-packages"])
SKIP_DIR_SUFFIXES = (".egg-info", ".dist-info")
SKIP_FILE_SUFFIXES = (".pyc", ".pyo")

USAGE = """\
사용법: pyumsn [옵션]... [파일.umsn | - | -c 코드] [인자]...
  또는: pyumsn -t|-u [-aq] [-x 패턴]... [--no-copy] [-o 출력] [파일|폴더]...
  또는: pyumsn -n [-q] [-x 패턴]... [파일|폴더]...
  또는: pyumsn -e [파일]...
  또는: pyumsn -w [-M] [검색어]...
  또는: pyumsn --translit 영어이름...  |  --untranslit 엄슨단어..."""

HELP = USAGE + """

엄슨(UMSN) 프로그래밍 언어 도구 — 실행, 엄슨 ↔ 파이썬 변환, 검사, IDE.

파일을 주면 실행합니다. 파일 뒤의 인자는 옵션처럼 보여도 모두 프로그램에 넘어갑니다.
폴더를 주면 그 안의 __main__.umsn 을 실행합니다 (python 폴더/ 와 같음).
파일이 없으면 터미널에서는 대화형 셸을 열고, 파이프로 들어오면 표준 입력을 실행합니다.

실행:
  -c, --command=코드     코드 문자열을 실행 (뒤의 인자는 프로그램에 넘김)
  -k, --keep             임시 파이썬 파일을 지우지 않음
  -p, --show-py          변환된 파이썬 코드를 먼저 보여줌 (표준 오류로)
  -i, --interactive      엄슨 대화형 셸 (엄>>>)
  -e, --ide, --edit      UMSN-IDE 로 파일 열기

변환·검사 (파일이 없거나 '-' 이면 표준 입력을 읽어 표준 출력으로):
  -t, --to-py            엄슨 → 파이썬 (파일.umsn → 파일.py)
  -u, --to-umsn          파이썬 → 엄슨 (파일.py → 파일.umsn)
  -n, --check            실행하지 않고 검사만 (영어 이름 등)
  -o, --output=경로      출력 파일 또는 폴더 ('-' 는 표준 출력).
                         피연산자가 여럿이면 폴더로 봅니다.
  -x, --exclude=패턴     (폴더) 이 이름·경로 패턴에 맞는 파일과 폴더는 건너뜀 (여러 번 가능)
      --no-copy          (폴더) 다른 폴더로 변환할 때 변환하지 않는 파일을 복사하지 않음
  -a, --ascii-symbols    (-u) 괄호·연산자 기호를 ASCII 그대로 둠 (--keep-symbols)
  -q, --quiet            성공 메시지를 출력하지 않음

폴더를 주면 안쪽 폴더까지 모두 들어가 프로젝트를 통째로 변환합니다. -o 로 다른 폴더에 만들면
자료 파일 등 나머지 파일도 같은 자리에 복사해서 그대로 실행할 수 있는 프로젝트가 됩니다.
.git, __pycache__, 가상 환경(.venv 등), node_modules, *.egg-info 같은 폴더는 건너뜁니다.

단어장:
  -w, --words            단어장 보기 (검색어를 주면 그 말이 든 단어만)
  -M, --markdown         단어장 전체를 마크다운 표로 (-w 를 뜻함)
      --translit         영어 이름 → 엄슨 음역
      --untranslit       엄슨 단어·음역 → 파이썬 이름

  -h, --help             이 도움말을 보여주고 끝냄
  -V, --version          버전을 보여주고 끝냄

짧은 옵션은 묶어 쓸 수 있고 (-tq), 긴 옵션은 헷갈리지 않을 만큼 줄여 쓸 수 있습니다 (--to-p).
'--' 뒤의 인자는 옵션으로 읽지 않습니다.

종료 상태: 0 성공, 1 오류, 2 잘못된 사용법. 실행할 때는 프로그램의 종료 상태.

예:
  pyumsn 안녕.umsn 가 나            안녕.umsn 실행 (sys.argv[1:] = ['가', '나'])
  pyumsn -t 안녕.umsn               안녕.py 만들기
  pyumsn -t < 안녕.umsn > 안녕.py   표준 입력 → 표준 출력
  pyumsn -ua hello.py               hello.umsn 만들기 (기호는 ASCII)
  pyumsn -u 내프로젝트 -o 엄슨프로젝트
                                    파이썬 프로젝트를 통째로 엄슨으로 (안쪽 폴더 포함)
  pyumsn -t 엄슨프로젝트 -o 되돌림 -x tests
                                    엄슨 프로젝트를 파이썬으로 (tests 는 건너뜀)
  pyumsn -n examples                폴더 안 .umsn 모두 검사
  pyumsn -c '엄!..하1 ..더해 2..다'
  echo '엄!..하"안녕"..다' | pyumsn
"""


class UsageError(Exception):
    """잘못된 명령줄 (종료 상태 2)."""


def _setup_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _say(text, err=False):
    stream = sys.stderr if err else sys.stdout
    stream.write(text + "\n")
    stream.flush()


def _write_stdout(text):
    """변환 결과를 표준 출력에 그대로 (윈도우에서도 줄바꿈을 바꾸지 않고) 쓴다."""
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _read_stdin():
    buffer = getattr(sys.stdin, "buffer", None)
    data = buffer.read() if buffer is not None else sys.stdin.read().encode("utf-8")
    return decode_source(data, STDIN_NAME)


def _report_error(exc):
    if isinstance(exc, UmsnSyntaxError):
        _say(exc.report(), err=True)
    else:
        _say("엄슨 오류! %s" % exc, err=True)


# ---------------------------------------------------------------------------
# 명령줄 읽기
# ---------------------------------------------------------------------------
_GETOPT_MESSAGES = [
    (r"option -(\S) not recognized", "알 수 없는 옵션 -- '%s'"),
    (r"option -(\S) requires argument", "옵션에 값이 필요하슨 -- '%s'"),
    (r"option --(\S+) not recognized", "알 수 없는 옵션 '--%s'"),
    (r"option --(\S+) not a unique prefix", "옵션 '--%s' 가 여러 옵션과 헷갈리슨"),
    (r"option --(\S+) requires argument", "옵션 '--%s' 에 값이 필요하슨"),
    (r"option --(\S+) must not have an argument", "옵션 '--%s' 에는 값을 줄 수 없슨"),
]


def _getopt_message(exc):
    for pattern, text in _GETOPT_MESSAGES:
        match = re.match(pattern, exc.msg)
        if match:
            return text % match.group(1)
    return exc.msg


def _getopt(argv, permute):
    parse = getopt.gnu_getopt if permute else getopt.getopt
    try:
        return parse(argv, SHORT_OPTS, LONG_OPTS)
    except getopt.GetoptError as exc:
        raise UsageError(_getopt_message(exc)) from None


class Options(object):
    def __init__(self):
        self.mode = None
        self.mode_opt = None
        self.code = None
        self.output = None
        self.excludes = []
        self.given = set()
        self.keep = self.show_py = self.keep_symbols = self.quiet = self.markdown = False
        self.no_copy = False
        self.help = self.version = False
        self.operands = []

    def set_mode(self, mode, opt):
        if self.mode is not None and self.mode != mode:
            raise UsageError("'%s' 와 '%s' 는 함께 쓸 수 없슨" % (self.mode_opt, opt))
        self.mode, self.mode_opt = mode, opt


def _collect(pairs, operands):
    opts = Options()
    for opt, value in pairs:
        if opt in ("-h", "--help"):
            opts.help = True
        elif opt in ("-V", "--version"):
            opts.version = True
        elif opt in _MODE_OPTS:
            opts.set_mode(_MODE_OPTS[opt], opt)
            if opt in ("-c", "--command"):
                opts.code = value
        elif opt in ("-o", "--output"):
            opts.output = value
            opts.given.add("output")
        elif opt in ("-x", "--exclude"):
            opts.excludes.append(value)
            opts.given.add("exclude")
        else:
            name = _FLAG_OPTS[opt]
            setattr(opts, name, True)
            opts.given.add(name)
    if opts.markdown and opts.mode is None:
        opts.set_mode("words", "-M")
    opts.operands = list(operands)
    return opts


def parse_args(argv):
    """명령줄을 읽어 :class:`Options` 를 돌려준다. 잘못되면 :class:`UsageError`."""
    opts = _collect(*_getopt(argv, permute=False))
    if opts.mode in _PERMUTE_MODES:
        # 파일을 여러 개 받는 모드는 옵션이 파일 뒤에 와도 된다 (POSIXLY_CORRECT 면 따르지 않음).
        opts = _collect(*_getopt(argv, permute=True))
    if opts.help or opts.version:
        return opts
    mode = opts.mode or "run"
    for name in sorted(opts.given):
        if mode not in _FLAG_MODES[name]:
            allowed = "·".join(_MODE_LABEL.get(m, "파일 실행") for m in _FLAG_MODES[name])
            raise UsageError("'%s' 는 %s 와 함께만 쓸 수 있슨" % (_FLAG_LABEL[name], allowed))
    if mode == "repl" and opts.operands:
        raise UsageError("'-i' 에는 파일을 줄 수 없슨 (실행하려면 'pyumsn 파일.umsn')")
    if mode in ("translit", "untranslit") and not opts.operands:
        raise UsageError("'%s' 에 바꿀 이름을 주세요" % _MODE_LABEL[mode])
    if mode == "words" and opts.markdown and opts.operands:
        raise UsageError("'-M' 은 검색어 없이 단어장 전체를 출력하슨")
    if mode == "run" and opts.operands:
        first = opts.operands[0]
        if first in _OLD_COMMANDS and not os.path.exists(first):
            raise UsageError("하위 명령 '%s' 는 없어졌슨. 대신 '%s' 를 쓰세요"
                             % (first, _OLD_COMMANDS[first]))
    return opts


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def _stdin_is_tty():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def cmd_run(opts):
    from .runner import run_file, run_source
    if not opts.operands:
        if _stdin_is_tty():
            return cmd_repl(opts)
        target, args = "-", []
    else:
        target, args = opts.operands[0], opts.operands[1:]
        main_file = os.path.join(target, "__main__.umsn")
        if os.path.isdir(target) and os.path.isfile(main_file):
            target = main_file
    try:
        if target == "-":
            return run_source(_read_stdin(), STDIN_NAME, args, keep=opts.keep, show_py=opts.show_py)
        return run_file(target, args, keep=opts.keep, show_py=opts.show_py)
    except FileNotFoundError:
        _say("엄슨 오류! 파일이 없슨: %s" % target, err=True)
        return 1
    except IsADirectoryError:
        _say("엄슨 오류! 폴더에 __main__.umsn 이 없어 실행할 수 없슨: %s" % target, err=True)
        return 1
    except UmsnError as exc:
        _report_error(exc)
        return 1


def cmd_command(opts):
    from .runner import run_source
    try:
        return run_source(opts.code, "<string>", opts.operands, keep=opts.keep, show_py=opts.show_py)
    except UmsnError as exc:
        _report_error(exc)
        return 1


def cmd_repl(opts):
    from .repl import main
    return main()


def cmd_ide(opts):
    from .runner import run_file
    try:
        return run_file(IDE_PATH, [os.path.abspath(f) for f in opts.operands])
    except UmsnError as exc:
        _report_error(exc)
        return 1


# ---------------------------------------------------------------------------
# 폴더(프로젝트) 훑기
# ---------------------------------------------------------------------------
def _matches(rel, name, patterns):
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in patterns)


def _skip_dir(path, name):
    if name in SKIP_DIRS or name.endswith(SKIP_DIR_SUFFIXES):
        return True
    return os.path.isfile(os.path.join(path, "pyvenv.cfg")) or os.path.isdir(os.path.join(path, "conda-meta"))


def walk_project(root, excludes=(), skip=()):
    """폴더 안의 파일을 안쪽 폴더까지 이름 순서로 돌려준다 (``(경로, 상대경로)``).

    :data:`SKIP_DIRS` 같은 폴더, ``excludes`` 패턴(이름이나 ``/`` 로 쓴 상대 경로)에 맞는 것,
    ``skip`` 에 든 폴더(출력 폴더 등)는 건너뛴다. 폴더 심볼릭 링크는 따라가지 않는다.
    """
    root = Path(root)
    skip = {os.path.normcase(str(Path(p).resolve())) for p in skip}
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel_base = base.relative_to(root)
        keep = []
        for name in sorted(dirnames):
            path = base / name
            rel = (rel_base / name).as_posix()
            if (_skip_dir(path, name) or _matches(rel, name, excludes)
                    or os.path.normcase(str(path.resolve())) in skip):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            rel = (rel_base / name).as_posix()
            if name.endswith(SKIP_FILE_SUFFIXES) or _matches(rel, name, excludes):
                continue
            yield base / name, rel_base / name


def _same_path(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path != root and root in path.parents


# ---------------------------------------------------------------------------
# 변환 (-t / -u)
# ---------------------------------------------------------------------------
def _translate(text, name, direction, keep_symbols):
    if direction == "topy":
        return umsn_to_py(text, filename=name)
    return py_to_umsn(text, filename=name, keep_symbols=keep_symbols)


def _emit(result, src_name, out_path, quiet):
    if out_path == "-":
        _write_stdout(result)
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_source(out_path, result)
    if not quiet:
        _say("만들었슨: %s → %s" % (src_name, out_path), err=True)


def _convert(opts, direction):
    src_suffix, dst_suffix = (".umsn", ".py") if direction == "topy" else (".py", ".umsn")
    operands = opts.operands or ["-"]
    output = opts.output
    many = len(operands) > 1
    if many and output and output != "-" and Path(output).is_file():
        _say("엄슨 오류! 여러 개를 변환할 때 '-o' 는 폴더여야 하슨: %s" % output, err=True)
        return 1
    failed = 0

    def convert(text_source, src_name, target):
        nonlocal failed
        try:
            text = text_source()
            _emit(_translate(text, src_name, direction, opts.keep_symbols), src_name, target, opts.quiet)
            return True
        except UmsnError as exc:
            failed += 1
            _report_error(exc)
        except OSError as exc:
            failed += 1
            _say("엄슨 오류! %s" % exc, err=True)
        return False

    for operand in operands:
        if operand == "-":
            target = output if (output and not many) else "-"
            convert(_read_stdin, STDIN_NAME, target)
            continue
        source = Path(operand)
        if not source.exists():
            _say("엄슨 오류! 파일이나 폴더가 없슨: %s" % source, err=True)
            failed += 1
            continue
        if source.is_dir():
            if output == "-":
                _say("엄슨 오류! 폴더는 표준 출력(-)으로 변환할 수 없슨: %s" % source, err=True)
                failed += 1
                continue
            if not output:
                out_root = source
            elif many:
                out_root = Path(output) / source.resolve().name
            else:
                out_root = Path(output)
            failed += _convert_tree(source, out_root, src_suffix, dst_suffix, opts, convert)
            continue
        if output == "-" or (output and not many):
            target = output
        elif output:
            target = Path(output) / source.with_suffix(dst_suffix).name
        else:
            target = source.with_suffix(dst_suffix)
        convert(lambda p=source: read_source(p), str(source), target)
    return 1 if failed else 0


def _convert_tree(source, out_root, src_suffix, dst_suffix, opts, convert):
    """폴더를 안쪽 폴더까지 통째로 변환한다. 돌려주는 값은 복사하다 실패한 파일 수.

    ``out_root`` 가 다른 폴더면 변환하지 않는 파일(자료, 설정 등)도 같은 자리에 복사해서
    그대로 실행할 수 있는 프로젝트를 만든다 (``--no-copy`` 면 복사하지 않음).
    """
    in_place = _same_path(source, out_root)
    skip = [out_root] if not in_place and _inside(out_root, source) else []
    sources, others = [], []
    for path, rel in walk_project(source, opts.excludes, skip):
        (sources if path.suffix == src_suffix else others).append((path, rel))
    if not sources and not opts.quiet:
        _say("변환할 %s 파일이 없슨: %s" % (src_suffix, source), err=True)
    made = set()
    converted = copied = bad = 0
    for path, rel in sources:
        target = out_root / rel.with_suffix(dst_suffix)
        made.add(os.path.normcase(str(target)))
        if convert(lambda p=path: read_source(p), str(path), target):
            converted += 1
        else:
            bad += 1
    copy_failed = 0
    if not in_place and not opts.no_copy:
        for path, rel in others:
            target = out_root / rel
            if os.path.normcase(str(target)) in made:
                if not opts.quiet:
                    _say("복사하지 않았슨: %s (변환한 파일과 이름이 겹침)" % path, err=True)
                continue
            if _same_path(path, target):
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied += 1
            except OSError as exc:
                copy_failed += 1
                _say("엄슨 오류! 복사하지 못했슨: %s (%s)" % (path, exc), err=True)
    if not opts.quiet and (sources or copied):
        summary = "변환 %d개" % converted
        if copied or (not in_place and not opts.no_copy):
            summary += ", 복사 %d개" % copied
        if bad or copy_failed:
            summary += ", 실패 %d개" % (bad + copy_failed)
        _say("폴더 %s → %s: %s" % (source, out_root, summary), err=True)
    return copy_failed


def cmd_topy(opts):
    return _convert(opts, "topy")


def cmd_toumsn(opts):
    return _convert(opts, "toumsn")


# ---------------------------------------------------------------------------
# 검사 (-n)
# ---------------------------------------------------------------------------
def cmd_check(opts):
    targets = []
    for operand in opts.operands or ["-"]:
        path = Path(operand)
        if operand != "-" and path.is_dir():
            targets += [str(p) for p, _ in walk_project(path, opts.excludes) if p.suffix == ".umsn"]
        else:
            targets.append(operand)
    bad = 0
    for name in targets:
        try:
            if name == "-":
                name, source = STDIN_NAME, _read_stdin()
            else:
                source = read_source(name)
        except (OSError, UmsnEncodingError) as exc:
            _say("엄슨 오류! %s" % exc, err=True)
            bad += 1
            continue
        problems = check_umsn(source)
        if problems:
            bad += 1
            _say(UmsnSyntaxError(problems, filename=name, source=source).report(), err=True)
        elif not opts.quiet:
            _say("문제 없슨! %s" % name)
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# 단어장 (-w / -M / --translit / --untranslit)
# ---------------------------------------------------------------------------
def _markdown_table():
    lines = ["# 엄슨(UMSN) 단어장", "",
             "`pyumsn --markdown` 으로 자동 생성한 문서입니다.", ""]
    groups = [("예약어", vocab.KEYWORDS), ("내장 함수·상수·예외", vocab.BUILTINS),
              ("관례·특수 이름", vocab.SPECIAL_NAMES), ("메소드·자주 쓰는 인자", vocab.METHODS)]
    groups += [("라이브러리 — " + title, table) for title, table in vocab.LIBRARY_GROUPS.items()]
    for title, table in groups:
        lines += ["## " + title, "", "| 엄슨 | 파이썬 |", "|---|---|"]
        lines += ["| `%s` | `%s` |" % (um, py) for py, um in table.items()]
        lines.append("")
    lines += ["## 기호 (문장부호·연산자)", "", "| 엄슨 | 파이썬 |", "|---|---|"]
    lines += ["| `%s` | `%s` |" % (um, py.replace("|", "\\|")) for py, um in vocab.SYMBOL2UMSN.items()]
    lines += ["", "`.` (속성 접근)과 `...` 은 그대로 씁니다.", ""]
    lines += ["## 문자열 접두사", "", "| 엄슨 | 파이썬 |", "|---|---|"]
    lines += ["| `%s\"...\"` | `%s\"...\"` |" % (um, py) for py, um in vocab.STRING_PREFIX_CHARS.items()]
    lines += ["", "대문자 접두사는 앞에 `대` 를 붙입니다 (`대형\"...\"` = `F\"...\"`). 조합 가능: `형날`=`fr`, `날바`=`rb`.", ""]
    lines += ["## 음역 (사전에 없는 영어 이름)", "",
              "표지 `%s` 뒤에 알파벳을 한 글자씩 한글 음절로 적습니다. 대문자는 앞에 `대`, 숫자와 `_` 는 그대로."
              % vocab.TRANSLIT_MARK, "", "| 알파벳 | 한글 |", "|---|---|"]
    lines += ["| `%s` | `%s` |" % (a, h) for a, h in vocab.TRANSLIT_LETTERS.items()]
    lines += ["", "예: `polyfit` → `%s`, `DataFrame` 이 사전에 없다면 `%s`" %
              (transliterate("polyfit"), transliterate("DataFrame")), ""]
    return "\n".join(lines)


def cmd_words(opts):
    if opts.markdown:
        _write_stdout(_markdown_table())
        return 0
    queries = [q.lower() for q in opts.operands]
    for title, um, py in vocab.all_words():
        if queries and not any(q in um.lower() or q in py.lower() or q in title.lower()
                               for q in queries):
            continue
        _say("%-18s %-22s %s" % (um, py, title))
    return 0


def cmd_translit(opts):
    bad = 0
    for name in opts.operands:
        if name in vocab.PY2UMSN:
            _say("%s → %s  (사전 단어)" % (name, vocab.PY2UMSN[name]))
            continue
        try:
            _say("%s → %s" % (name, transliterate(name)))
        except ValueError as exc:
            _say("엄슨 오류! %s" % exc, err=True)
            bad += 1
    return 1 if bad else 0


def cmd_untranslit(opts):
    bad = 0
    for word in opts.operands:
        py = vocab.UMSN2PY.get(word) or vocab.UMSN2SYMBOL.get(word) or untransliterate(word)
        if py:
            _say("%s → %s" % (word, py))
        else:
            _say("엄슨 오류! '%s' 는 엄슨 단어나 음역이 아니슨" % word, err=True)
            bad += 1
    return 1 if bad else 0


COMMANDS = {
    "run": cmd_run, "command": cmd_command, "repl": cmd_repl, "ide": cmd_ide,
    "topy": cmd_topy, "toumsn": cmd_toumsn, "check": cmd_check,
    "words": cmd_words, "translit": cmd_translit, "untranslit": cmd_untranslit,
}


def main(argv=None):
    _setup_stdio()
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        opts = parse_args(argv)
    except UsageError as exc:
        _say("%s: %s" % (PROG, exc), err=True)
        _say("자세한 사용법은 '%s --help' 를 보세요." % PROG, err=True)
        return 2
    if opts.help:
        _write_stdout(HELP)
        return 0
    if opts.version:
        _say("PyUMSN %s" % __version__)
        return 0
    try:
        return COMMANDS[opts.mode or "run"](opts)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # pyumsn -w | head 처럼 읽는 쪽이 먼저 닫혀도 조용히 끝낸다
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
