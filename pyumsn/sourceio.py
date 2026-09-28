"""UTF-8 전용 소스 입출력.

엄슨은 내부에서 무조건 UTF-8 만 쓴다. 다른 인코딩은 추측하거나 대체하지 않고 거부한다.
"""

import codecs
import re
from pathlib import Path

from .errors import UmsnEncodingError

_CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
_UTF8_NAMES = {"utf-8", "utf8", "utf_8", "utf-8-sig", "utf8-sig", "utf_8_sig", "u8"}


def decode_source(data, filename="<소스>"):
    """바이트를 UTF-8 로 엄격하게 디코딩한다 (BOM 은 허용하고 제거)."""
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE,
                          codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise UmsnEncodingError(
            "%s: UTF-16/UTF-32 파일은 쓸 수 없슨! UTF-8 로 저장하세요." % filename)
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        lineno = data.count(b"\n", 0, exc.start) + 1
        raise UmsnEncodingError(
            "%s: UTF-8 이 아닌 파일은 쓸 수 없슨! (%d줄, %d번째 바이트) "
            "파일을 UTF-8 로 저장하세요." % (filename, lineno, exc.start)) from None
    for line in text.splitlines()[:2]:
        match = _CODING_RE.match(line)
        if match:
            name = match.group(1).lower()
            if name not in _UTF8_NAMES:
                raise UmsnEncodingError(
                    "%s: 인코딩 선언 '%s' 는 쓸 수 없슨! 엄슨은 UTF-8 만 씁니다."
                    % (filename, match.group(1)))
            break
    return text


def read_source(path):
    """파일을 UTF-8 로 읽는다. 줄바꿈(CRLF 등)은 그대로 보존한다."""
    path = Path(path)
    return decode_source(path.read_bytes(), str(path))


def write_source(path, text):
    """BOM 없는 UTF-8 로 쓴다. 줄바꿈은 주어진 그대로."""
    path = Path(path)
    path.write_bytes(text.encode("utf-8"))
    return path
