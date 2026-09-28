"""엄슨 ↔ 파이썬 변환기.

토큰 단위로만 바꾸므로 줄 번호가 그대로 유지된다.
주석과 문자열(docstring 포함)은 한 글자도 바꾸지 않는다.
"""

from . import vocab
from .errors import UmsnSyntaxError
from .lexer import (MODE_PY, MODE_UMSN, Lexer, is_hangul_name, py_prefix_to_umsn,
                    tokenize, umsn_prefix_to_py)

_CODE_KINDS = frozenset(["name", "word", "dollar", "number", "op", "sigil"])


# ---------------------------------------------------------------------------
# 음역:  polyfit ↔ 외_피오르야프이트
# ---------------------------------------------------------------------------
def transliterate(name):
    """영어(ASCII) 이름을 한글 음역으로. 사전에 있는 이름도 음역만 한다."""
    out = [vocab.TRANSLIT_MARK]
    for ch in name:
        low = ch.lower()
        if low in vocab.TRANSLIT_LETTERS:
            syl = vocab.TRANSLIT_LETTERS[low]
            out.append(vocab.UPPER_MARK + syl if ch.isupper() else syl)
        elif ch == "_" or ch in "0123456789":
            out.append(ch)
        else:
            raise ValueError("음역할 수 없는 글자: %r" % ch)
    return "".join(out)


def untransliterate(word):
    """``외_…`` 음역을 영어 이름으로 되돌린다. 음역 형태가 아니면 None."""
    mark = vocab.TRANSLIT_MARK
    if not word.startswith(mark) or len(word) == len(mark):
        return None
    out = []
    i = len(mark)
    n = len(word)
    while i < n:
        ch = word[i]
        if ch == "_" or ch in "0123456789":
            out.append(ch)
            i += 1
            continue
        upper = False
        if ch == vocab.UPPER_MARK:
            upper = True
            i += 1
            if i >= n:
                return None
            ch = word[i]
        letter = vocab.TRANSLIT_REVERSE.get(ch)
        if letter is None:
            return None
        out.append(letter.upper() if upper else letter)
        i += 1
    result = "".join(out)
    if not any(c.isalpha() for c in result) or result[0] in "0123456789":
        return None
    return result


def suggest_name(name):
    """영어 이름을 쓴 사람에게 보여줄 제안."""
    if name in vocab.PY2UMSN:
        return vocab.PY2UMSN[name]
    try:
        return transliterate(name)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 이름 변환
# ---------------------------------------------------------------------------
def _umsn_name_to_py(text):
    """(파이썬 이름, 오류메시지) 를 돌려준다."""
    py = vocab.UMSN2PY.get(text)
    if py is not None:
        return py, None
    py = untransliterate(text)
    if py is not None:
        return py, None
    if is_hangul_name(text) or all(ch == "_" for ch in text):
        return text, None
    if any(ch.isascii() and ch.isalpha() for ch in text):
        hint = suggest_name(text) if text.isascii() else None
        msg = "영어 이름 '%s' 는 쓸 수 없슨! 한글 이름을 쓰세요." % text
        if hint:
            msg = "영어 이름 '%s' 는 쓸 수 없슨! 한글 이름을 쓰거나 '%s' 를 쓰세요." % (text, hint)
        return text, msg
    return text, "이름 '%s' 에 한글이 아닌 글자가 있슨! 엄슨 이름은 한글·숫자·_ 만 됩니다." % text


def _py_name_to_umsn(text):
    um = vocab.PY2UMSN.get(text)
    if um is not None:
        return um
    if text.isascii():
        if not any(ch.isalpha() for ch in text):
            return text
        return transliterate(text)
    if is_hangul_name(text):
        if text in vocab.UMSN2PY or untransliterate(text) is not None:
            return "$" + text
        return text
    return None


# ---------------------------------------------------------------------------
# 엄슨 → 파이썬
# ---------------------------------------------------------------------------
def _umsn_tokens_to_py(tokens):
    out = []
    problems = []
    for tok in tokens:
        kind = tok.kind
        text = tok.text
        if kind == "name":
            py, err = _umsn_name_to_py(text)
            if err:
                problems.append((tok.start, len(text), err))
            out.append(py)
        elif kind == "word":
            out.append(vocab.UMSN2PY[text])
        elif kind == "dollar":
            name = text[1:]
            if not is_hangul_name(name):
                problems.append((tok.start, len(text),
                                 "'$' 탈출 이름 '%s' 는 한글이어야 합니다." % name))
            out.append(name)
        elif kind == "sigil":
            out.append(vocab.UMSN2SYMBOL[text])
        elif kind in ("string", "fstart") and tok.prefix:
            py_prefix = umsn_prefix_to_py(tok.prefix)
            if py_prefix is None:
                problems.append((tok.start, len(tok.prefix),
                                 "영문 문자열 접두사 '%s' 는 쓸 수 없슨!" % tok.prefix))
                py_prefix = tok.prefix
            out.append(py_prefix + text[len(tok.prefix):])
        elif kind == "error":
            problems.append((tok.start, len(text), "알 수 없는 엄슨 기호어 '%s' 입니다." % text))
            out.append(text)
        else:
            out.append(text)
    return "".join(out), problems


def umsn_to_py(src, filename=None):
    """엄슨 소스를 파이썬 소스로 바꾼다. 문제가 있으면 (모든 문제를 담은) UmsnSyntaxError."""
    lexer = Lexer(src, MODE_UMSN)
    try:
        tokens = lexer.run()
    except UmsnSyntaxError as exc:
        raise UmsnSyntaxError(check_umsn(src) or exc.problems, filename=filename, source=src,
                              incomplete=exc.incomplete) from None
    py, problems = _umsn_tokens_to_py(tokens)
    if problems:
        raise UmsnSyntaxError(_located(lexer, problems), filename=filename, source=src)
    return py


class PositionMap(object):
    """변환된 파이썬 코드의 (줄, 칸) 을 엄슨 소스의 칸으로 되돌린다 (오류 표시용)."""

    def __init__(self, umsn_src):
        from bisect import bisect_right
        self._bisect = bisect_right
        self.umsn_src = umsn_src
        lexer = Lexer(umsn_src, MODE_UMSN, tolerant=True)
        tokens = lexer.run()
        self._lexer = lexer
        py_parts = []
        self._py_starts = []
        self._tokens = []
        pos = 0
        for tok in tokens:
            text, _ = _umsn_tokens_to_py([tok])
            self._py_starts.append(pos)
            self._tokens.append((tok.start, tok.end, len(text)))
            py_parts.append(text)
            pos += len(text)
        self.py_src = "".join(py_parts)
        self._py_line_starts = [0] + [i + 1 for i, ch in enumerate(self.py_src) if ch == "\n"]

    def py_line(self, lineno):
        lines = self.py_src.splitlines()
        return lines[lineno - 1] if 1 <= lineno <= len(lines) else ""

    def umsn_col(self, lineno, py_col, end=False):
        """파이썬 (줄, 칸[문자 단위]) → 엄슨 칸. 모르면 None."""
        if not (1 <= lineno <= len(self._py_line_starts)) or py_col is None:
            return None
        off = self._py_line_starts[lineno - 1] + py_col
        idx = self._bisect(self._py_starts, off) - 1
        if idx < 0:
            return None
        if end and idx > 0 and off == self._py_starts[idx]:
            idx -= 1  # 끝 위치는 앞 토큰의 끝으로
        um_start, um_end, py_len = self._tokens[idx]
        delta = off - self._py_starts[idx]
        if py_len == um_end - um_start:
            um_off = um_start + delta
        elif delta >= py_len:
            um_off = um_end
        else:
            um_off = um_start
        l, c = self._lexer.line_col(um_off)
        return c if l == lineno else None


def _located(lexer, problems):
    result = []
    for start, length, msg in problems:
        lineno, col = lexer.line_col(start)
        result.append((lineno, col, length, msg))
    return result


def check_umsn(src):
    """엄슨 소스의 모든 문제를 ``[(줄, 칸, 길이, 메시지), ...]`` 로 돌려준다 (없으면 빈 목록)."""
    lexer = Lexer(src, MODE_UMSN)
    try:
        tokens = lexer.run()
    except UmsnSyntaxError as exc:
        # 렉서 단계 오류가 있으면 관대 모드로 나머지 문제도 모은다.
        tol = Lexer(src, MODE_UMSN, tolerant=True)
        _, problems = _umsn_tokens_to_py(tol.run())
        merged = {}
        for prob in exc.problems + _located(tol, problems):
            merged.setdefault((prob[0], prob[1]), prob)
        return sorted(merged.values(), key=lambda p: (p[0] or 0, p[1] or 0))
    _, problems = _umsn_tokens_to_py(tokens)
    return _located(lexer, problems)


# ---------------------------------------------------------------------------
# 파이썬 → 엄슨
# ---------------------------------------------------------------------------
def _py_pieces(tokens, keep_symbols, lexer):
    """(kind, 엄슨텍스트) 조각 목록."""
    pieces = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        kind = tok.kind
        text = tok.text
        if kind == "name":
            um = _py_name_to_umsn(text)
            if um is None:
                lineno, col = lexer.line_col(tok.start)
                raise UmsnSyntaxError(
                    [(lineno, col, len(text),
                      "파이썬 이름 '%s' 는 엄슨으로 바꿀 수 없슨! (한글 또는 영어 이름만 가능)" % text)],
                    source=lexer.src)
            pieces.append(("name", um))
        elif kind in ("string", "fstart") and tok.prefix:
            um = py_prefix_to_umsn(tok.prefix)
            if um is None:
                lineno, col = lexer.line_col(tok.start)
                raise UmsnSyntaxError([(lineno, col, len(tok.prefix),
                                        "알 수 없는 문자열 접두사 '%s'" % tok.prefix)],
                                      source=lexer.src)
            pieces.append((kind, um + text[len(tok.prefix):]))
        elif kind == "op" and not keep_symbols and tok.fdepth == 0:
            nxt = tokens[i + 1] if i + 1 < n else None
            pair = text + nxt.text if nxt is not None and nxt.kind == "op" else None
            if pair in ("()", "[]", "{}"):
                pieces.append(("sigil", vocab.SYMBOL2UMSN[pair]))
                i += 2
                continue
            um = vocab.SYMBOL2UMSN.get(text)
            pieces.append(("sigil", um) if um else ("op", text))
        else:
            pieces.append((kind, text))
        i += 1
    return pieces


def _lexes_as(a, b):
    """엄슨 렉서가 a+b 를 정확히 [a, b] 로 나누는가."""
    try:
        toks = Lexer(a + b, MODE_UMSN).run()
    except UmsnSyntaxError:
        return False
    return len(toks) == 2 and toks[0].text == a and toks[1].text == b


def _join(pieces, force_space=False):
    out = []
    prev = None
    for kind, text in pieces:
        if prev is not None and kind in _CODE_KINDS and prev[0] in _CODE_KINDS:
            if force_space or not _lexes_as(prev[1], text):
                out.append(" ")
        out.append(text)
        prev = (kind, text)
    return "".join(out)


def _significant(tokens):
    return [t.text for t in tokens if t.kind != "ws"]


def py_to_umsn(src, filename=None, keep_symbols=False):
    """파이썬 소스를 엄슨 소스로 바꾼다.

    ``keep_symbols=True`` 이면 괄호·연산자 같은 기호는 ASCII 그대로 둔다.
    사전에 없는 영어 이름은 ``외_…`` 로 음역되므로 결과는 항상 한글 전용 규칙을 지킨다.
    """
    lexer = Lexer(src, MODE_PY)
    try:
        tokens = lexer.run()
        pieces = _py_pieces(tokens, keep_symbols, lexer)
    except UmsnSyntaxError as exc:
        exc.filename = filename
        exc.args = (exc._format(),)
        raise
    expected = _significant(tokens)
    for force in (False, True):
        out = _join(pieces, force_space=force)
        try:
            back = umsn_to_py(out)
            if _significant(tokenize(back, MODE_PY)) == expected:
                return out
        except UmsnSyntaxError:
            pass
    raise UmsnSyntaxError("파이썬 → 엄슨 변환 결과를 되돌려 확인하지 못했슨 (변환기 버그일 수 있습니다).",
                          filename=filename)


# ---------------------------------------------------------------------------
# IDE 용: 구문 강조 구간
# ---------------------------------------------------------------------------
def highlight_spans(src):
    """구문 강조용 ``[(분류, 시작줄, 시작칸, 끝줄, 끝칸), ...]``.

    분류: keyword builtin special method library bang translit dollar
          symbol op number string fbrace comment error
    줄은 1부터, 칸은 0부터 센다 (Tkinter Text 인덱스와 같음).
    """
    lexer = Lexer(src, MODE_UMSN, tolerant=True)
    try:
        tokens = lexer.run()
    except UmsnSyntaxError:
        return []
    spans = []
    for tok in tokens:
        kind = tok.kind
        cat = None
        if kind == "ws":
            continue
        if kind == "comment":
            cat = "comment"
        elif kind in ("string", "fstart", "fmiddle", "fend"):
            cat = "string"
        elif kind in ("fopen", "fclose"):
            cat = "fbrace"
        elif kind == "number":
            cat = "number"
        elif kind == "sigil":
            cat = "symbol"
        elif kind == "word":
            cat = "bang"
        elif kind == "dollar":
            cat = "dollar"
        elif kind == "op":
            cat = "op"
        elif kind == "error":
            cat = "error"
        elif kind == "name":
            cat = vocab.category_of(tok.text)
            if cat is None:
                if untransliterate(tok.text) is not None:
                    cat = "translit"
                elif not (is_hangul_name(tok.text) or all(c == "_" for c in tok.text)):
                    cat = "error"
        if cat is None:
            continue
        l1, c1 = lexer.line_col(tok.start)
        l2, c2 = lexer.line_col(tok.end)
        spans.append((cat, l1, c1, l2, c2))
        if kind in ("string", "fstart") and tok.prefix and umsn_prefix_to_py(tok.prefix) is None:
            spans.append(("error", l1, c1, l1, c1 + len(tok.prefix)))
    return spans


def tokenize_umsn(src, tolerant=True):
    """엄슨 소스를 토큰 목록으로 (IDE 괄호 짝 맞추기 등에 사용)."""
    return tokenize(src, MODE_UMSN, tolerant=tolerant)
