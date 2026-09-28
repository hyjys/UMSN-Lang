import ast
import glob
import os
import sys

import pytest

from pyumsn import (UmsnSyntaxError, check_umsn, highlight_spans, py_to_umsn, transliterate,
                    umsn_to_py, untransliterate)


def roundtrip(py, **kw):
    um = py_to_umsn(py, **kw)
    assert check_umsn(um) == []
    return um, umsn_to_py(um)


def test_hello():
    assert umsn_to_py('엄!..하"안녕 엄슨"..다') == 'print("안녕 엄슨")'
    assert py_to_umsn('print("안녕 엄슨")') == '엄!..하"안녕 엄슨"..다'


def test_def_if_return():
    um = "엄슨하다 판정..하수..다..한\n    어엄슨 수 ..크슨 0..한\n        엄슨한 엄슨참\n    엄슨한 슨엄거짓\n"
    assert umsn_to_py(um) == "def 판정(수):\n    if 수 > 0:\n        return True\n    return False\n"


def test_strings_comments_docstrings_untouched():
    py = '"""def print if"""\nx = "print(1)"  # print if def\ny = \'return\'\n'
    um, back = roundtrip(py)
    assert '"""def print if"""' in um
    assert '"print(1)"' in um
    assert "# print if def" in um
    assert "'return'" in um
    assert back == py


def test_fstring_expressions_translated():
    um, back = roundtrip('print(f"{len(a)!r:>{w}} {x=} {{literal}}")')
    assert '형"{엄길이(' in um
    assert "{{literal}}" in um
    assert back == 'print(f"{len(a)!r:>{w}} {x=} {{literal}}")'


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 701")
def test_fstring_nested_same_quote():
    py = "x = f'{', '.join(a)}'\n"
    _, back = roundtrip(py)
    assert back == py


def test_string_prefixes():
    um, back = roundtrip("a = rb'\\d' + Rb'x'\nb = F'{1}'\nc = u'x'\n")
    assert "날바'\\d'" in um
    assert "대날바'x'" in um
    assert "대형'{1}'" in um
    assert "유'x'" in um
    assert back == "a = rb'\\d' + Rb'x'\nb = F'{1}'\nc = u'x'\n"


def test_numbers_and_ellipsis():
    py = "a = [1.5, .5, 1e-3, 0x1F, 3j, 1_000, ...][1:]\nb = 1..real\n"
    um, back = roundtrip(py)
    assert ast.dump(ast.parse(back)) == ast.dump(ast.parse(py))


def test_composite_brackets():
    assert py_to_umsn("f()") == "외_프..하다"
    assert py_to_umsn("a = []") == "외_아 ..은 ..엄슨"
    assert py_to_umsn("a = {}") == "외_아 ..은 ..어엄슨"
    assert umsn_to_py("엄목록..하..다") == "list()"


def test_glue_space_inserted_when_needed():
    # "..하" + "다음" 을 붙이면 "..하다" + "음" 으로 읽히므로 공백이 들어간다.
    um = py_to_umsn("f(다음)")
    assert um == "외_프..하 다음..다"
    assert umsn_to_py(um) == "f( 다음)"


def test_keep_symbols():
    assert py_to_umsn("print(a[0])", keep_symbols=True) == "엄!(외_아[0])"


def test_bang_word_vs_not_equal():
    assert umsn_to_py("엄 != 1") == "pass != 1"
    assert umsn_to_py("엄!..하1..다") == "print(1)"


def test_dollar_escape():
    um, back = roundtrip("엄슨 = 1\n외_아 = 2\n")
    assert um.startswith("$엄슨 ..은 1")
    assert "$외_아" in um
    assert back == "엄슨 = 1\n외_아 = 2\n"


def test_transliteration():
    assert transliterate("linalg") == "외_르이느아르그"
    assert untransliterate("외_르이느아르그") == "linalg"
    for name in ("DataFrame2", "_private", "__dunder__", "XYZ", "a_b_c9"):
        assert untransliterate(transliterate(name)) == name
    assert untransliterate("외_점수") is None
    assert untransliterate("점수") is None


def test_english_names_rejected():
    with pytest.raises(UmsnSyntaxError) as info:
        umsn_to_py("점수 ..은 1\ncount ..은 2\nprint..하점수x..다\n")
    err = info.value
    msgs = [p[3] for p in err.problems]
    assert (err.lineno, err.col) == (2, 0)
    assert len(err.problems) == 3
    assert "count" in msgs[0] and "엄세어" in msgs[0]
    assert "'엄!'" in msgs[1]
    assert "점수x" in msgs[2]


def test_non_hangul_names_rejected():
    with pytest.raises(UmsnSyntaxError):
        umsn_to_py("π ..은 3.14\n")
    with pytest.raises(UmsnSyntaxError):
        py_to_umsn("café = 1\n")


def test_english_string_prefix_rejected():
    with pytest.raises(UmsnSyntaxError) as info:
        umsn_to_py('엄!..하f"{1}"..다')
    assert "형" in info.value.msg


def test_english_inside_fstring_rejected():
    with pytest.raises(UmsnSyntaxError):
        umsn_to_py('엄!..하형"{count}"..다')


def test_unknown_sigil():
    with pytest.raises(UmsnSyntaxError) as info:
        umsn_to_py("가 ..엉터리 1")
    assert "기호어" in info.value.msg


def test_unterminated_string():
    with pytest.raises(UmsnSyntaxError) as info:
        umsn_to_py('엄!..하"안녕..다\n')
    assert not info.value.incomplete
    with pytest.raises(UmsnSyntaxError) as info:
        umsn_to_py('가 ..은 """안녕\n')
    assert info.value.incomplete


def test_line_numbers_preserved():
    py = "a = 1\n\n\ndef f(x):\n    '''doc\n    string'''\n    return x\n"
    um, back = roundtrip(py)
    assert um.count("\n") == py.count("\n")
    assert back == py


def test_crlf_preserved():
    py = "a = 1\r\nif a:\r\n    print(a)\r\n"
    _, back = roundtrip(py)
    assert back == py


def test_check_umsn_ok():
    assert check_umsn("엄!..하1..다") == []


def test_highlight_spans():
    spans = highlight_spans('엄슨하다 가..하다..한 # 주석\n    엄!..하"글"..다 count\n')
    cats = [s[0] for s in spans]
    for cat in ("keyword", "symbol", "comment", "bang", "string", "error"):
        assert cat in cats, cat
    assert ("keyword", 1, 0, 1, 4) in spans


STDLIB = os.path.dirname(ast.__file__)
SAMPLES = sorted(glob.glob(os.path.join(STDLIB, "*.py")))[:60]


@pytest.mark.parametrize("path", SAMPLES, ids=os.path.basename)
def test_stdlib_roundtrip(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        src = data.decode("utf-8")
        ast.parse(src)
    except (UnicodeDecodeError, SyntaxError):
        pytest.skip("원본이 이 파이썬에서 파싱되지 않음")
    for keep in (False, True):
        um = py_to_umsn(src, keep_symbols=keep)
        assert check_umsn(um) == []
        back = umsn_to_py(um)
        assert ast.dump(ast.parse(back)) == ast.dump(ast.parse(src))
