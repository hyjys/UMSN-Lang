"""PyUMSN — 엄슨(UMSN) 프로그래밍 언어.

    >>> import pyumsn
    >>> pyumsn.umsn_to_py('엄!..하"안녕 엄슨"..다')
    'print("안녕 엄슨")'
    >>> pyumsn.py_to_umsn('print("안녕 엄슨")')
    '엄!..하"안녕 엄슨"..다'
"""

__version__ = "1.0.1"

from .errors import UmsnEncodingError, UmsnError, UmsnSyntaxError  # noqa: E402
from .sourceio import read_source, write_source  # noqa: E402
from .translator import (check_umsn, highlight_spans, py_to_umsn,  # noqa: E402
                         tokenize_umsn, transliterate, umsn_to_py, untransliterate)
from .vocab import all_words, category_of  # noqa: E402

__all__ = [
    "__version__", "UmsnError", "UmsnSyntaxError", "UmsnEncodingError",
    "umsn_to_py", "py_to_umsn", "check_umsn", "highlight_spans", "tokenize_umsn",
    "transliterate", "untransliterate", "read_source", "write_source",
    "all_words", "category_of", "run_file", "install_import_hook",
]


def run_file(path, args=(), keep=False):
    """엄슨 파일을 실행하고 종료 코드를 돌려준다."""
    from .runner import run_file as _run
    return _run(path, list(args), keep=keep)


def install_import_hook():
    """``import`` 로 ``.umsn`` 모듈을 불러올 수 있게 한다."""
    from .importer import install
    install()
