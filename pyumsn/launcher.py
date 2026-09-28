"""하위 프로세스 진입점.

    python -X utf8 -m pyumsn.launcher <임시.py> <원본.umsn> [인자...]

임시 파이썬 파일을 원본 ``.umsn`` 파일 이름으로 컴파일해서 실행한다.
변환 전후 줄 번호가 같으므로 오류 트레이스백이 엄슨 소스 줄을 그대로 보여준다.
"""

import builtins
import os
import sys
import traceback
import types

_SYNTAX_HINTS = [
    ("expected ':'", "'..한' (:) 이 빠졌슨"),
    ("invalid syntax", "문법이 잘못됐슨"),
    ("unexpected indent", "들여쓰기가 이상하슨"),
    ("expected an indented block", "들여쓴 블록이 필요하슨"),
    ("unindent does not match", "내어쓰기 위치가 맞지 않슨"),
    ("was never closed", "괄호가 닫히지 않았슨"),
    ("unmatched", "짝이 없는 괄호가 있슨"),
    ("unterminated string", "문자열이 닫히지 않았슨"),
    ("cannot assign", "여기에는 값을 넣을 수 없슨"),
    ("Perhaps you forgot a comma", "'..고' (,) 를 빠뜨린 것 같슨"),
]


def _setup_stdio():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _korean_name(exc_type):
    from . import vocab
    from .translator import transliterate
    name = exc_type.__name__
    if name in vocab.PY2UMSN:
        return vocab.PY2UMSN[name]
    try:
        return transliterate(name)
    except ValueError:
        return name


_MAPS = {}


def _position_map(filename):
    """엄슨 파일의 PositionMap (없거나 엄슨 파일이 아니면 None)."""
    if not filename.lower().endswith(".umsn"):
        return None
    if filename not in _MAPS:
        try:
            from .sourceio import read_source
            from .translator import PositionMap
            _MAPS[filename] = PositionMap(read_source(filename))
        except Exception:
            _MAPS[filename] = None
    return _MAPS[filename]


def _width(text):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _caret_line(line, start, end):
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    if start is None or end is None or end <= start or start < indent:
        return None
    if start == indent and end >= len(line.rstrip()):
        return None
    return "    " + " " * _width(line[indent:start]) + "^" * max(1, _width(line[start:end]))


def _byte_to_char(line, col):
    if col is None:
        return None
    return len(line.encode("utf-8")[:col].decode("utf-8", "replace"))


def _format_frame(fs):
    import linecache
    out = ['  File "%s", line %s, in %s\n' % (fs.filename, fs.lineno, fs.name)]
    line = linecache.getline(fs.filename, fs.lineno).rstrip("\r\n")
    if not line.strip():
        return out
    out.append("    %s\n" % line.strip())
    colno = getattr(fs, "colno", None)
    end_colno = getattr(fs, "end_colno", None)
    if colno is None or end_colno is None or getattr(fs, "end_lineno", fs.lineno) != fs.lineno:
        return out
    pmap = _position_map(fs.filename)
    if pmap is not None:
        py_line = pmap.py_line(fs.lineno)
        start = pmap.umsn_col(fs.lineno, _byte_to_char(py_line, colno))
        end = pmap.umsn_col(fs.lineno, _byte_to_char(py_line, end_colno), end=True)
    else:
        start, end = _byte_to_char(line, colno), _byte_to_char(line, end_colno)
    caret = _caret_line(line, start, end)
    if caret:
        out.append(caret + "\n")
    return out


def _report_syntax(exc, umsn_path):
    hint = None
    for key, text in _SYNTAX_HINTS:
        if key in (exc.msg or ""):
            hint = text
            break
    col = None
    line = None
    pmap = _position_map(umsn_path)
    if pmap is not None and exc.lineno:
        lines = pmap.umsn_src.splitlines()
        if 1 <= exc.lineno <= len(lines):
            line = lines[exc.lineno - 1]
        if exc.offset:
            col = pmap.umsn_col(exc.lineno, exc.offset - 1)
    where = "%s %s줄" % (umsn_path, exc.lineno)
    if col is not None:
        where += " %d칸" % (col + 1)
    sys.stderr.write("엄슨 오류! 문법 오류 (%s): %s\n" % (where, hint or exc.msg))
    if hint:
        sys.stderr.write("    (파이썬: %s)\n" % exc.msg)
    if line is not None:
        sys.stderr.write("    %s\n" % line)
        if col is not None:
            sys.stderr.write("    %s^\n" % (" " * _width(line[:col])))
    sys.stderr.flush()


def _report(exc, _seen=None, outer=True):
    _seen = _seen if _seen is not None else set()
    _seen.add(id(exc))
    if exc.__cause__ is not None and id(exc.__cause__) not in _seen:
        _report(exc.__cause__, _seen, False)
        sys.stderr.write("\n위 예외가 아래 예외의 직접적인 원인이었슨:\n\n")
    elif (exc.__context__ is not None and not exc.__suppress_context__
          and id(exc.__context__) not in _seen):
        _report(exc.__context__, _seen, False)
        sys.stderr.write("\n위 예외를 처리하는 동안 또 다른 예외가 일어났슨:\n\n")
    tb = exc.__traceback__
    here = os.path.abspath(__file__)
    while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) == here:
        tb = tb.tb_next
    sys.stderr.write("엄슨 추적 기록 (가장 최근 호출이 마지막):\n")
    for fs in traceback.extract_tb(tb):
        for piece in _format_frame(fs):
            sys.stderr.write(piece)
    for line in traceback.format_exception_only(type(exc), exc):
        sys.stderr.write(line)
    if outer:
        sys.stderr.write("엄슨 오류! %s (%s): %s\n" % (_korean_name(type(exc)), type(exc).__name__, exc))
    sys.stderr.flush()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) < 2:
        sys.stderr.write("사용법: python -m pyumsn.launcher <임시.py> <원본.umsn> [인자...]\n")
        return 2
    _setup_stdio()
    from .importer import install
    from .sourceio import read_source

    py_path, umsn_path = argv[0], os.path.abspath(argv[1])
    source = read_source(py_path)
    if not os.environ.pop("PYUMSN_KEEP_TEMP", None):
        try:
            os.remove(py_path)  # 이미 읽었으니 임시 파일은 바로 지운다
        except OSError:
            pass
    sys.argv = [umsn_path] + argv[2:]
    if sys.path and sys.path[0] in ("", os.getcwd()):
        sys.path[0] = os.path.dirname(umsn_path)
    else:
        sys.path.insert(0, os.path.dirname(umsn_path))
    install()

    # 문법 검사는 임시 .py 이름으로 한다: 실제 .umsn 파일 이름을 주면 파이썬이
    # 오류 칸 번호를 (파이썬 코드가 아닌) 엄슨 줄 기준으로 다시 계산해 버린다.
    try:
        compile(source, py_path, "exec")
    except SyntaxError as exc:
        _report_syntax(exc, umsn_path)
        return 1
    code = compile(source, umsn_path, "exec")

    keep_alive = sys.modules.get("__main__")  # noqa: F841 (실행 중인 모듈 유지)
    module = types.ModuleType("__main__")
    module.__file__ = umsn_path
    module.__builtins__ = builtins
    sys.modules["__main__"] = module
    try:
        exec(code, module.__dict__)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.stderr.write("\n엄슨 중단! (Ctrl+C)\n")
        return 130
    except BaseException as exc:  # noqa: B902
        from .errors import UmsnError, UmsnSyntaxError
        if isinstance(exc, UmsnSyntaxError):
            sys.stderr.write(exc.report() + "\n")
        elif isinstance(exc, UmsnError):
            sys.stderr.write("엄슨 오류! %s\n" % exc)
        else:
            _report(exc)
        return 1
    finally:
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
