"""``.umsn`` 모듈 불러오기 (import hook).

``엄슨가져와 내모듈`` 은 ``sys.path`` 에서 ``내모듈.umsn`` (또는 ``내모듈/__init__.umsn``) 을 찾는다.
"""

import importlib.abc
import importlib.util
import os
import sys

from .sourceio import read_source
from .translator import umsn_to_py

SUFFIX = ".umsn"


class UmsnLoader(importlib.abc.Loader):
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = read_source(self.path)
        py = umsn_to_py(source, filename=self.path)
        try:
            compile(py, "<엄슨 %s>" % self.path, "exec")
        except SyntaxError as exc:
            raise syntax_error_to_umsn(exc, source, self.path) from None
        code = compile(py, self.path, "exec")
        module.__file__ = self.path
        exec(code, module.__dict__)


class UmsnFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        name = fullname.rpartition(".")[2]
        search = sys.path if path is None else path
        for entry in list(search):
            if not isinstance(entry, str):
                continue
            base = entry or os.getcwd()
            pkg_init = os.path.join(base, name, "__init__" + SUFFIX)
            if os.path.isfile(pkg_init):
                return importlib.util.spec_from_file_location(
                    fullname, pkg_init, loader=UmsnLoader(pkg_init),
                    submodule_search_locations=[os.path.join(base, name)])
            candidate = os.path.join(base, name + SUFFIX)
            if os.path.isfile(candidate):
                return importlib.util.spec_from_file_location(
                    fullname, candidate, loader=UmsnLoader(candidate))
        return None


def syntax_error_to_umsn(exc, umsn_source, filename):
    """파이썬 SyntaxError 를 엄슨 줄·칸 기준의 UmsnSyntaxError 로."""
    from .errors import UmsnSyntaxError
    from .translator import PositionMap
    col = None
    if exc.lineno and exc.offset:
        col = PositionMap(umsn_source).umsn_col(exc.lineno, exc.offset - 1)
    return UmsnSyntaxError([(exc.lineno, col, 1, "파이썬 문법 오류: %s" % exc.msg)],
                           filename=filename, source=umsn_source)


def install():
    """import hook 을 한 번만 설치한다."""
    if not any(isinstance(f, UmsnFinder) for f in sys.meta_path):
        sys.meta_path.append(UmsnFinder())
