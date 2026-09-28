import keyword

from pyumsn import vocab
from pyumsn.lexer import is_hangul, is_hangul_name
from pyumsn.translator import untransliterate


def _core(word):
    """느낌표/물음표를 뗀 단어."""
    return word[:-1] if word[-1] in "!?" else word


def test_all_python_keywords_are_translated():
    for kw in keyword.kwlist:
        assert kw in vocab.PY2UMSN, kw


def test_bijective():
    assert len(set(vocab.PY2UMSN.values())) == len(vocab.PY2UMSN)
    assert len(set(vocab.SYMBOL2UMSN.values())) == len(vocab.SYMBOL2UMSN)
    for py, um in vocab.PY2UMSN.items():
        assert vocab.UMSN2PY[um] == py


def test_words_are_hangul_only():
    for um in vocab.UMSN2PY:
        core = _core(um)
        assert is_hangul_name(core), um
        assert core.isidentifier(), um
        assert untransliterate(core) is None, um


def test_bang_words_only_for_known_builtins():
    bang = {um: py for um, py in vocab.UMSN2PY.items() if um[-1] in "!?"}
    assert bang["엄!"] == "print"
    assert bang["엄?"] == "input"


def test_symbol_words():
    for um in vocab.UMSN2SYMBOL:
        assert um.startswith("..")
        assert all(is_hangul(ch) for ch in um[2:]), um
    assert vocab.SYMBOL2UMSN["()"] == "..하다"
    assert vocab.SYMBOL2UMSN[":"] == "..한"


def test_user_examples():
    assert vocab.PY2UMSN["def"] == "엄슨하다"
    assert vocab.PY2UMSN["if"] == "어엄슨"
    assert vocab.PY2UMSN["return"] == "엄슨한"
    assert vocab.PY2UMSN["print"] == "엄!"


def test_library_names_have_umsn():
    for lib in ("tkinter", "numpy", "pandas", "matplotlib"):
        assert vocab.PY2UMSN[lib].endswith("엄슨"), lib


def test_translit_table_distinct():
    values = list(vocab.TRANSLIT_LETTERS.values())
    assert len(set(values)) == 26
    assert vocab.UPPER_MARK not in values
