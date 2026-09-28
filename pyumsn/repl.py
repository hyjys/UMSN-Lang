"""엄슨 대화형 셸."""

import code
import sys

from . import __version__
from .errors import UmsnSyntaxError
from .importer import install
from .translator import umsn_to_py


class UmsnConsole(code.InteractiveConsole):
    def runsource(self, source, filename="<엄슨>", symbol="single"):
        try:
            py = umsn_to_py(source)
        except UmsnSyntaxError as exc:
            if exc.incomplete:
                return True
            self.write(exc.report() + "\n")
            return False
        return code.InteractiveConsole.runsource(self, py, filename, symbol)


def main():
    install()
    sys.ps1 = "엄>>> "
    sys.ps2 = "엄... "
    banner = ("엄슨 %s (파이썬 %s)\n"
              "끝내려면 엄나가..하다 또는 Ctrl+D (윈도우: Ctrl+Z 후 Enter)"
              % (__version__, sys.version.split()[0]))
    UmsnConsole(locals={"__name__": "__main__"}).interact(banner=banner, exitmsg="엄슨 안녕!")
    return 0
