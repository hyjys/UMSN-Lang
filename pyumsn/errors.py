"""엄슨 오류 클래스."""


class UmsnError(Exception):
    """PyUMSN 의 모든 오류의 부모."""


class UmsnEncodingError(UmsnError):
    """UTF-8 이 아닌 소스 파일."""


class UmsnSyntaxError(UmsnError):
    """엄슨 문법 오류 (영어 이름, 알 수 없는 기호어, 닫히지 않은 문자열 등).

    ``problems`` 에는 ``(줄번호, 칸번호, 길이, 메시지)`` 목록이 들어 있고,
    대표 오류는 그중 첫 번째이다. 줄번호는 1부터, 칸번호는 0부터 센다.
    """

    def __init__(self, problems, filename=None, source=None, incomplete=False):
        if isinstance(problems, str):
            problems = [(None, None, 0, problems)]
        self.problems = list(problems)
        self.filename = filename
        self.source = source
        self.incomplete = incomplete
        first = self.problems[0]
        self.lineno, self.col, self.length, self.msg = first
        super().__init__(self._format())

    def line_text(self, lineno):
        if self.source is None or lineno is None:
            return None
        lines = self.source.splitlines()
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1]
        return None

    def _where(self, lineno, col):
        parts = []
        if self.filename:
            parts.append(str(self.filename))
        if lineno is not None:
            parts.append("%d줄 %d칸" % (lineno, (col or 0) + 1))
        return " ".join(parts)

    def _format(self):
        where = self._where(self.lineno, self.col)
        text = "엄슨 문법 오류"
        if where:
            text += " (%s)" % where
        text += ": " + self.msg
        if len(self.problems) > 1:
            text += " (외 %d개)" % (len(self.problems) - 1)
        return text

    def report(self):
        """모든 문제를 사람이 읽기 좋게 여러 줄로 만든다."""
        out = []
        for lineno, col, length, msg in self.problems:
            where = self._where(lineno, col)
            out.append("엄슨 문법 오류%s: %s" % (" (%s)" % where if where else "", msg))
            line = self.line_text(lineno)
            if line is not None:
                col = col or 0
                out.append("    " + line.replace("\t", "    "))
                pad = _display_width(line[:col].replace("\t", "    "))
                mark = max(1, _display_width(line[col:col + (length or 1)]))
                out.append("    " + " " * pad + "^" * mark)
        return "\n".join(out)


def _display_width(text):
    """터미널 표시 폭 (한글 등 전각 문자는 2칸)."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)
