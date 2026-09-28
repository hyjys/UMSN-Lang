"""엄슨/파이썬 공통 렉서.

소스를 토큰으로 나누되, 공백·주석·문자열은 원문 그대로 보존한다.
토큰 텍스트를 순서대로 이어 붙이면 항상 원래 소스와 같다.

토큰 종류(kind)
    ws       공백, 줄바꿈, 줄 잇기(``\\`` + 줄바꿈)
    comment  ``#`` 주석
    string   일반 문자열 (접두사 포함)            .prefix
    fstart   f-string 시작 (접두사 + 여는 따옴표)   .prefix
    fmiddle  f-string 의 글자 부분, 변환(!r), 서식 지정자, 디버그 ``=``
    fopen    f-string 치환 필드 ``{``
    fclose   f-string 치환 필드 ``}``
    fend     f-string 닫는 따옴표
    name     이름(식별자)
    word     ``엄!`` / ``엄?`` 처럼 느낌표·물음표로 끝나는 엄슨 단어
    dollar   ``$이름`` (엄슨 탈출 이름)
    number   숫자
    sigil    ``..한`` 같은 엄슨 기호어
    op       연산자·문장부호 (ASCII)
    error    알 수 없는 기호어 (관대 모드에서만)

``fdepth`` 가 0 보다 크면 f-string 치환 필드 안의 식이다.
"""

from bisect import bisect_right

from . import vocab
from .errors import UmsnSyntaxError

MODE_UMSN = "umsn"
MODE_PY = "py"

_OPERATORS = sorted([
    "**=", "//=", ">>=", "<<=", "...", "->", ":=", "**", "//", ">>", "<<",
    "<=", ">=", "==", "!=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "@=",
    "+", "-", "*", "/", "%", "@", "&", "|", "^", "~", "<", ">",
    "(", ")", "[", "]", "{", "}", ",", ":", ".", ";", "=", "!",
], key=len, reverse=True)

_OPEN = {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}
_DIGITS = "0123456789"
_PY_PREFIXES = {"r", "u", "f", "b", "t", "br", "rb", "fr", "rf", "tr", "rt"}


class Token(object):
    __slots__ = ("kind", "text", "start", "end", "prefix", "fdepth")

    def __init__(self, kind, text, start, end, prefix=None, fdepth=0):
        self.kind = kind
        self.text = text
        self.start = start
        self.end = end
        self.prefix = prefix
        self.fdepth = fdepth

    def __repr__(self):
        return "Token(%s, %r)" % (self.kind, self.text)


def is_hangul(ch):
    o = ord(ch)
    return (0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3131 <= o <= 0x318E
            or 0xA960 <= o <= 0xA97F or 0xD7B0 <= o <= 0xD7FF)


def is_hangul_name(text):
    """한글(음절·자모) + 숫자 + ``_`` 로만 된 이름인가."""
    return bool(text) and all(is_hangul(ch) or ch == "_" or ch in _DIGITS for ch in text) \
        and text[0] not in _DIGITS


def _id_start(ch):
    return ch == "_" or ch.isidentifier()


def _id_char(ch):
    return ch == "_" or ("a" + ch).isidentifier()


# ---------------------------------------------------------------------------
# 문자열 접두사 변환
# ---------------------------------------------------------------------------
def umsn_prefix_to_py(prefix):
    """``형날`` → ``fr``, ``대형`` → ``F``. 올바르지 않으면 None."""
    out = []
    i = 0
    while i < len(prefix):
        upper = False
        if prefix[i] == vocab.UPPER_MARK:
            upper = True
            i += 1
            if i >= len(prefix):
                return None
        ch = vocab.PREFIX_REVERSE.get(prefix[i])
        if ch is None:
            return None
        out.append(ch.upper() if upper else ch)
        i += 1
    result = "".join(out)
    if result.lower() not in _PY_PREFIXES:
        return None
    return result


def py_prefix_to_umsn(prefix):
    out = []
    for ch in prefix:
        syl = vocab.STRING_PREFIX_CHARS.get(ch.lower())
        if syl is None:
            return None
        out.append(vocab.UPPER_MARK + syl if ch.isupper() else syl)
    return "".join(out)


class Lexer(object):
    def __init__(self, src, mode, tolerant=False):
        self.src = src
        self.n = len(src)
        self.mode = mode
        self.tolerant = tolerant
        self.tokens = []
        self._line_starts = None

    # -- 위치 계산 --------------------------------------------------------
    def line_col(self, pos):
        if self._line_starts is None:
            starts = [0]
            src = self.src
            i = src.find("\n")
            while i != -1:
                starts.append(i + 1)
                i = src.find("\n", i + 1)
            self._line_starts = starts
        idx = bisect_right(self._line_starts, pos) - 1
        return idx + 1, pos - self._line_starts[idx]

    def fail(self, msg, pos, length=1, incomplete=False):
        lineno, col = self.line_col(pos)
        raise UmsnSyntaxError([(lineno, col, length, msg)], source=self.src,
                              incomplete=incomplete)

    def emit(self, kind, start, end, prefix=None, fdepth=0):
        self.tokens.append(Token(kind, self.src[start:end], start, end, prefix, fdepth))

    # -- 진입점 -----------------------------------------------------------
    def run(self):
        self._code(0, 0, None)
        return self.tokens

    # -- 코드 -------------------------------------------------------------
    def _code(self, pos, fdepth, fquote):
        """코드를 토큰으로 나눈다. f-string 식 안이면 종결 문자에서 멈추고 위치를 돌려준다."""
        src, n = self.src, self.n
        depth = 0
        umsn = self.mode == MODE_UMSN
        while pos < n:
            c = src[pos]
            if fdepth and depth <= 0:
                # PEP 701: 필드 안의 따옴표는 (바깥과 같은 따옴표라도) 중첩 문자열의 시작이다.
                if c in "}:" or (c == "!" and src[pos + 1:pos + 2] != "="):
                    return pos
            # 공백
            if c in " \t\f\r\n":
                end = pos + 1
                while end < n and src[end] in " \t\f\r\n":
                    end += 1
                self.emit("ws", pos, end, fdepth=fdepth)
                pos = end
                continue
            if c == "\\" and src[pos + 1:pos + 2] in ("\n", "\r"):
                end = pos + 2
                if src[pos + 1:pos + 3] == "\r\n":
                    end = pos + 3
                self.emit("ws", pos, end, fdepth=fdepth)
                pos = end
                continue
            # 주석
            if c == "#":
                end = pos
                while end < n and src[end] not in "\r\n":
                    end += 1
                self.emit("comment", pos, end, fdepth=fdepth)
                pos = end
                continue
            # 문자열 (접두사 없음)
            if c in "\"'":
                pos = self._string(pos, pos, "", fdepth)
                continue
            # 탈출 이름 $이름
            if c == "$" and umsn:
                end = pos + 1
                if end < n and _id_start(src[end]):
                    end += 1
                    while end < n and _id_char(src[end]):
                        end += 1
                    self.emit("dollar", pos, end, fdepth=fdepth)
                    pos = end
                    continue
                if self.tolerant:
                    self.emit("error", pos, pos + 1, fdepth=fdepth)
                    pos += 1
                    continue
                self.fail("'$' 뒤에는 한글 이름이 와야 합니다.", pos)
            # 이름 / 단어 / 접두사 문자열
            if _id_start(c):
                end = pos + 1
                while end < n and _id_char(src[end]):
                    end += 1
                name = src[pos:end]
                nxt = src[end:end + 1]
                if nxt and nxt in "\"'":
                    if umsn:
                        if umsn_prefix_to_py(name) is not None:
                            pos = self._string(pos, end, name, fdepth)
                            continue
                        if name.lower() in _PY_PREFIXES:
                            if not self.tolerant:
                                self.fail("영문 문자열 접두사 '%s' 는 쓸 수 없슨! %s 처럼 한글 접두사를 쓰세요."
                                          % (name, (py_prefix_to_umsn(name) or "형") + nxt + "..." + nxt),
                                          pos, len(name))
                            pos = self._string(pos, end, name, fdepth, py_prefix=name)
                            continue
                    elif name.lower() in _PY_PREFIXES:
                        pos = self._string(pos, end, name, fdepth)
                        continue
                if umsn and nxt and nxt in "!?":
                    word = name + nxt
                    if word in vocab.UMSN2PY and not (nxt == "!" and src[end + 1:end + 2] == "="):
                        self.emit("word", pos, end + 1, fdepth=fdepth)
                        pos = end + 1
                        continue
                self.emit("name", pos, end, fdepth=fdepth)
                pos = end
                continue
            # 숫자
            if c in _DIGITS or (c == "." and pos + 1 < n and src[pos + 1] in _DIGITS):
                end = self._number(pos)
                self.emit("number", pos, end, fdepth=fdepth)
                pos = end
                continue
            # 엄슨 기호어 ..한
            if umsn and c == "." and src[pos + 1:pos + 2] == "." and pos + 2 < n and is_hangul(src[pos + 2]):
                for word in vocab.SYMBOL_WORDS_BY_LENGTH:
                    if src.startswith(word, pos):
                        self.emit("sigil", pos, pos + len(word), fdepth=fdepth)
                        depth += _OPEN.get(vocab.UMSN2SYMBOL[word], 0)
                        pos += len(word)
                        break
                else:
                    end = pos + 2
                    while end < n and _id_char(src[end]):
                        end += 1
                    if self.tolerant:
                        self.emit("error", pos, end, fdepth=fdepth)
                        pos = end
                        continue
                    self.fail("알 수 없는 엄슨 기호어 '%s' 입니다." % src[pos:end], pos, end - pos)
                continue
            # 연산자
            for op in _OPERATORS:
                if src.startswith(op, pos):
                    break
            else:
                op = c
            if fdepth and depth <= 0 and op == "=":
                # f"{x=}" 디버그 표시
                look = pos + 1
                while look < n and src[look] in " \t":
                    look += 1
                if src[look:look + 1] in ("}", "!", ":") and src[look:look + 1]:
                    return pos
            self.emit("op", pos, pos + len(op), fdepth=fdepth)
            depth += _OPEN.get(op, 0)
            pos += len(op)
        if fdepth and not self.tolerant:
            self.fail("f-string 의 중괄호 '{' 가 닫히지 않았슨!", pos, incomplete=True)
        return pos

    # -- 숫자 -------------------------------------------------------------
    def _number(self, pos):
        src, n = self.src, self.n
        i = pos
        if src[i] == "0" and src[i + 1:i + 2] in ("x", "X", "o", "O", "b", "B") and src[i + 1:i + 2]:
            i += 2
            while i < n and (src[i] in _DIGITS or src[i] == "_" or ("a" <= src[i].lower() <= "f")):
                i += 1
            return i
        while i < n and (src[i] in _DIGITS or src[i] == "_"):
            i += 1
        if i < n and src[i] == ".":
            if not (self.mode == MODE_UMSN and src[i + 1:i + 2] == "."):
                i += 1
                while i < n and (src[i] in _DIGITS or src[i] == "_"):
                    i += 1
        if i < n and src[i] in "eE":
            j = i + 1
            if j < n and src[j] in "+-":
                j += 1
            if j < n and src[j] in _DIGITS:
                i = j
                while i < n and (src[i] in _DIGITS or src[i] == "_"):
                    i += 1
        if i < n and src[i] in "jJ":
            i += 1
        return i

    # -- 문자열 -----------------------------------------------------------
    def _string(self, start, qpos, prefix, fdepth, py_prefix=None):
        """start: 접두사 시작, qpos: 여는 따옴표 위치. 끝난 위치를 돌려준다."""
        src, n = self.src, self.n
        if py_prefix is None:
            py_prefix = umsn_prefix_to_py(prefix) if (self.mode == MODE_UMSN and prefix) else prefix
        low = (py_prefix or "").lower()
        raw = "r" in low
        is_f = "f" in low or "t" in low
        q = src[qpos]
        quote = q * 3 if src.startswith(q * 3, qpos) else q
        triple = len(quote) == 3
        pos = qpos + len(quote)
        if not is_f:
            while True:
                if pos >= n:
                    self._unterminated(start, triple)
                    self.emit("string", start, n, prefix=prefix, fdepth=fdepth)
                    return n
                c = src[pos]
                if c == "\\":
                    pos += 2
                    continue
                if src.startswith(quote, pos):
                    pos += len(quote)
                    self.emit("string", start, pos, prefix=prefix, fdepth=fdepth)
                    return pos
                if c in "\r\n" and not triple:
                    self._unterminated(start, False)
                    self.emit("string", start, pos, prefix=prefix, fdepth=fdepth)
                    return pos
                pos += 1
        # f-string
        self.emit("fstart", start, pos, prefix=prefix, fdepth=fdepth)
        return self._fbody(pos, quote, raw, fdepth, start, in_spec=False)

    def _unterminated(self, start, triple):
        if not self.tolerant:
            self.fail("문자열이 닫히지 않았슨!", start, 1, incomplete=triple)

    def _fbody(self, pos, quote, raw, fdepth, start, in_spec):
        """f-string 본문(또는 서식 지정자)을 처리한다."""
        src, n = self.src, self.n
        triple = len(quote) == 3
        lit = pos

        def flush(upto):
            if upto > lit:
                self.emit("fmiddle", lit, upto, fdepth=fdepth)

        while True:
            if pos >= n:
                flush(n)
                if not self.tolerant:
                    self.fail("문자열이 닫히지 않았슨!", start, 1, incomplete=triple)
                return n
            c = src[pos]
            if c == "\\":
                if not raw and src.startswith("N{", pos + 1):
                    close = src.find("}", pos)
                    pos = close + 1 if close != -1 else n
                else:
                    pos += 2
                continue
            if in_spec and c == "}":
                flush(pos)
                return pos
            if not in_spec and src.startswith(quote, pos):
                flush(pos)
                self.emit("fend", pos, pos + len(quote), fdepth=fdepth)
                return pos + len(quote)
            if c in "\r\n" and not triple:
                flush(pos)
                if not self.tolerant:
                    self.fail("문자열이 닫히지 않았슨!", start)
                return pos
            if not in_spec and c in "{}" and src[pos + 1:pos + 2] == c:
                pos += 2
                continue
            if c == "{":
                flush(pos)
                pos = self._field(pos, quote, raw, fdepth, start)
                lit = pos
                continue
            pos += 1

    def _field(self, pos, quote, raw, fdepth, start):
        """``{`` 부터 짝이 맞는 ``}`` 까지."""
        src, n = self.src, self.n
        self.emit("fopen", pos, pos + 1, fdepth=fdepth)
        pos = self._code(pos + 1, fdepth + 1, quote)
        lit = pos
        if pos < n and src[pos] == "=":
            pos += 1
            while pos < n and src[pos] in " \t":
                pos += 1
        if pos < n and src[pos] == "!":
            pos += 1
            while pos < n and src[pos].isalpha():
                pos += 1
        if pos > lit:
            self.emit("fmiddle", lit, pos, fdepth=fdepth)
        if pos < n and src[pos] == ":":
            pos = self._fbody(pos, quote, raw, fdepth, start, in_spec=True)
        if pos < n and src[pos] == "}":
            self.emit("fclose", pos, pos + 1, fdepth=fdepth)
            return pos + 1
        if not self.tolerant:
            self.fail("f-string 의 중괄호 '{' 가 닫히지 않았슨!", pos, incomplete=pos >= n)
        return pos


def tokenize(src, mode=MODE_UMSN, tolerant=False):
    """소스를 토큰 목록으로 나눈다."""
    return Lexer(src, mode, tolerant).run()
