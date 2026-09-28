"""``pyumsn`` 명령줄 도구."""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, vocab
from .errors import UmsnEncodingError, UmsnError, UmsnSyntaxError
from .sourceio import read_source, write_source
from .translator import check_umsn, py_to_umsn, transliterate, umsn_to_py, untransliterate

IDE_PATH = Path(__file__).resolve().parent / "ide" / "umsn_ide.umsn"


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


# ---------------------------------------------------------------------------
# 변환 (topy / toumsn)
# ---------------------------------------------------------------------------
def _convert_one(src_path, out_path, direction, keep_symbols):
    text = read_source(src_path)
    if direction == "topy":
        result = umsn_to_py(text, filename=str(src_path))
    else:
        result = py_to_umsn(text, filename=str(src_path), keep_symbols=keep_symbols)
    if out_path == "-":
        sys.stdout.write(result)
        sys.stdout.flush()
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_source(out_path, result)
    _say("만들었슨: %s → %s" % (src_path, out_path), err=True)


def _convert(args, direction):
    src_suffix, dst_suffix = (".umsn", ".py") if direction == "topy" else (".py", ".umsn")
    source = Path(args.source)
    if not source.exists():
        _say("엄슨 오류! 파일이나 폴더가 없슨: %s" % source, err=True)
        return 1
    keep = getattr(args, "keep_symbols", False)
    failed = 0
    if source.is_dir():
        if args.output == "-":
            _say("엄슨 오류! 폴더는 표준 출력(-)으로 변환할 수 없슨.", err=True)
            return 1
        out_root = Path(args.output) if args.output else source
        files = sorted(p for p in source.rglob("*" + src_suffix) if p.is_file())
        if not files:
            _say("변환할 %s 파일이 없슨: %s" % (src_suffix, source), err=True)
        for path in files:
            target = out_root / path.relative_to(source).with_suffix(dst_suffix)
            try:
                _convert_one(path, target, direction, keep)
            except UmsnError as exc:
                failed += 1
                _report_error(exc)
        return 1 if failed else 0
    out = args.output or str(source.with_suffix(dst_suffix))
    try:
        _convert_one(source, out, direction, keep)
    except UmsnError as exc:
        _report_error(exc)
        return 1
    return 0


def _report_error(exc):
    if isinstance(exc, UmsnSyntaxError):
        _say(exc.report(), err=True)
    else:
        _say("엄슨 오류! %s" % exc, err=True)


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------
def cmd_run(args):
    from .runner import run_file
    try:
        return run_file(args.file, args.args, keep=args.keep, show_py=args.show_py)
    except FileNotFoundError:
        _say("엄슨 오류! 파일이 없슨: %s" % args.file, err=True)
        return 1
    except UmsnError as exc:
        _report_error(exc)
        return 1


def cmd_topy(args):
    return _convert(args, "topy")


def cmd_toumsn(args):
    return _convert(args, "toumsn")


def cmd_check(args):
    bad = 0
    for name in args.files:
        try:
            source = read_source(name)
        except (OSError, UmsnEncodingError) as exc:
            _say("엄슨 오류! %s" % exc, err=True)
            bad += 1
            continue
        problems = check_umsn(source)
        if problems:
            bad += 1
            _say(UmsnSyntaxError(problems, filename=name, source=source).report(), err=True)
        else:
            _say("문제 없슨! %s" % name)
    return 1 if bad else 0


def cmd_ide(args):
    from .runner import run_file
    extra = [os.path.abspath(args.file)] if args.file else []
    try:
        return run_file(IDE_PATH, extra)
    except UmsnError as exc:
        _report_error(exc)
        return 1


def cmd_repl(args):
    from .repl import main
    return main()


def _markdown_table():
    lines = ["# 엄슨(UMSN) 단어장", "",
             "`pyumsn words --markdown` 으로 자동 생성한 문서입니다.", ""]
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


def cmd_words(args):
    if args.translit:
        for name in args.translit:
            if name in vocab.PY2UMSN:
                _say("%s → %s  (사전 단어)" % (name, vocab.PY2UMSN[name]))
            else:
                try:
                    _say("%s → %s" % (name, transliterate(name)))
                except ValueError as exc:
                    _say("엄슨 오류! %s" % exc, err=True)
                    return 1
        return 0
    if args.untranslit:
        for word in args.untranslit:
            py = vocab.UMSN2PY.get(word) or vocab.UMSN2SYMBOL.get(word) or untransliterate(word)
            _say("%s → %s" % (word, py if py else "(엄슨 단어/음역이 아닙니다)"))
        return 0
    if args.markdown:
        sys.stdout.write(_markdown_table())
        return 0
    query = (args.search or "").lower()
    for title, um, py in vocab.all_words():
        if query and query not in um.lower() and query not in py.lower() and query not in title.lower():
            continue
        _say("%-18s %-22s %s" % (um, py, title))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pyumsn",
        description="엄슨(UMSN) 프로그래밍 언어 도구 — 엄슨 ↔ 파이썬 변환, 실행, IDE",
        epilog="예) pyumsn run 안녕.umsn  |  pyumsn topy 안녕.umsn  |  pyumsn toumsn hello.py  |  pyumsn ide")
    parser.add_argument("--version", "-V", action="version", version="PyUMSN %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="명령")

    p = sub.add_parser("run", help="엄슨 파일 실행 (임시 파이썬 파일을 만들어 실행)")
    p.add_argument("file", help=".umsn 파일")
    p.add_argument("args", nargs=argparse.REMAINDER, help="프로그램에 넘길 인자")
    p.add_argument("--keep", action="store_true", help="임시 파이썬 파일을 지우지 않음")
    p.add_argument("--show-py", action="store_true", help="변환된 파이썬 코드를 먼저 보여줌")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("topy", help="엄슨 → 파이썬 변환 (파일 또는 폴더)")
    p.add_argument("source", help=".umsn 파일 또는 폴더")
    p.add_argument("-o", "--output", help="출력 파일/폴더 ('-' 는 화면)")
    p.set_defaults(func=cmd_topy)

    p = sub.add_parser("toumsn", help="파이썬 → 엄슨 변환 (파일 또는 폴더)")
    p.add_argument("source", help=".py 파일 또는 폴더")
    p.add_argument("-o", "--output", help="출력 파일/폴더 ('-' 는 화면)")
    p.add_argument("--keep-symbols", action="store_true", help="괄호·연산자 기호는 ASCII 그대로 둠")
    p.set_defaults(func=cmd_toumsn)

    p = sub.add_parser("check", help="엄슨 파일 검사 (영어 이름 등)")
    p.add_argument("files", nargs="+", help=".umsn 파일")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("ide", help="UMSN-IDE 실행")
    p.add_argument("file", nargs="?", help="열 파일")
    p.set_defaults(func=cmd_ide)

    p = sub.add_parser("repl", help="엄슨 대화형 셸")
    p.set_defaults(func=cmd_repl)

    p = sub.add_parser("words", help="엄슨 단어장 보기 / 음역")
    p.add_argument("--search", "-s", help="찾을 말 (엄슨 또는 파이썬)")
    p.add_argument("--markdown", action="store_true", help="마크다운 표로 출력")
    p.add_argument("--translit", nargs="+", metavar="영어이름", help="영어 이름 → 엄슨 음역")
    p.add_argument("--untranslit", nargs="+", metavar="엄슨단어", help="엄슨 단어/음역 → 파이썬")
    p.set_defaults(func=cmd_words)
    return parser


def main(argv=None):
    _setup_stdio()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0].lower().endswith(".umsn"):
        argv = ["run"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
