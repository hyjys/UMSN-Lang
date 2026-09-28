import codecs
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import pyumsn
from pyumsn import UmsnEncodingError, read_source, umsn_to_py, write_source
from pyumsn.cli import IDE_PATH

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def pyumsn_cmd(*args, input_text=None, cwd=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, "-m", "pyumsn"] + [str(a) for a in args],
                          input=(input_text or "").encode("utf-8"), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, cwd=cwd, timeout=120)


def out(res):
    return res.stdout.decode("utf-8"), res.stderr.decode("utf-8")


def temp_files():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "umsn_*.py")))


def test_run_hello():
    res = pyumsn_cmd("run", EXAMPLES / "안녕.umsn", input_text="엄슨\n")
    stdout, stderr = out(res)
    assert res.returncode == 0, stderr
    assert "안녕, 엄슨!" in stdout
    assert "반가워요, 엄슨님!" in stdout


def test_shorthand_and_args(tmp_path):
    prog = tmp_path / "인자.umsn"
    write_source(prog, "엄슨가져와 시스템엄슨\n엄!..하시스템엄슨.인자목록엄슨..엄1..한..슨..다\n")
    res = pyumsn_cmd(prog, "가", "나")
    assert res.returncode == 0, out(res)[1]
    assert "['가', '나']" in out(res)[0]


def test_run_exit_code(tmp_path):
    prog = tmp_path / "끝.umsn"
    write_source(prog, "엄슨가져와 시스템엄슨\n시스템엄슨.엄나가..하3..다\n")
    assert pyumsn_cmd("run", prog).returncode == 3


def test_run_rejects_english_before_running(tmp_path):
    prog = tmp_path / "영어.umsn"
    write_source(prog, '엄!..하"실행되면 안 됨"..다\ncount ..은 1\n')
    before = temp_files()
    res = pyumsn_cmd("run", prog)
    stdout, stderr = out(res)
    assert res.returncode == 1
    assert "실행되면 안 됨" not in stdout
    assert "영어 이름 'count'" in stderr
    assert "2줄 1칸" in stderr
    assert temp_files() == before


def test_runtime_error_points_to_umsn_line(tmp_path):
    prog = tmp_path / "오류.umsn"
    write_source(prog, "가 ..은 1\n\n엄!..하가 ..나눠 0..다\n")
    res = pyumsn_cmd("run", prog)
    stderr = out(res)[1]
    assert res.returncode == 1
    assert 'line 3' in stderr
    assert "엄!..하가 ..나눠 0..다" in stderr
    assert "엄영나누기오류" in stderr


def test_python_syntax_error_reported(tmp_path):
    prog = tmp_path / "문법.umsn"
    write_source(prog, "어엄슨 엄슨참\n    엄!..하1..다\n")
    res = pyumsn_cmd("run", prog)
    stderr = out(res)[1]
    assert res.returncode == 1
    assert "1줄 8칸" in stderr
    assert "어엄슨 엄슨참" in stderr
    if sys.version_info >= (3, 10):  # 옛 파이썬은 그냥 "invalid syntax"
        assert "..한" in stderr


def test_temp_file_removed_and_keep():
    before = temp_files()
    assert pyumsn_cmd("run", EXAMPLES / "구구단.umsn").returncode == 0
    assert temp_files() == before
    res = pyumsn_cmd("run", "--keep", EXAMPLES / "구구단.umsn")
    kept = temp_files() - before
    assert len(kept) == 1
    path = kept.pop()
    assert "def 구구단(단):" in read_source(path)
    os.remove(path)


def test_import_umsn_module(tmp_path):
    write_source(tmp_path / "계산기.umsn", "엄슨하다 더하기..하가..고 나..다..한\n    엄슨한 가 ..더해 나\n")
    write_source(tmp_path / "메인.umsn", "엄슨가져와 계산기\n엄!..하계산기.더하기..하2..고 3..다..다\n")
    res = pyumsn_cmd("run", tmp_path / "메인.umsn")
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].strip() == "5"


def test_topy_and_toumsn_files(tmp_path):
    src = tmp_path / "hello.py"
    write_source(src, 'def greet(name):\n    return f"hi {name}"\n\nprint(greet("엄슨"))\n')
    assert pyumsn_cmd("toumsn", src).returncode == 0
    um = read_source(tmp_path / "hello.umsn")
    assert "엄슨하다" in um
    assert pyumsn_cmd("topy", tmp_path / "hello.umsn", "-o", tmp_path / "back.py").returncode == 0
    assert read_source(tmp_path / "back.py") == read_source(src)
    res = pyumsn_cmd("run", tmp_path / "hello.umsn")
    assert out(res)[0].strip() == "hi 엄슨"


def test_topy_stdout_and_directory(tmp_path):
    res = pyumsn_cmd("topy", EXAMPLES / "구구단.umsn", "-o", "-")
    assert "def 구구단(단):" in out(res)[0]
    res = pyumsn_cmd("topy", EXAMPLES, "-o", tmp_path / "py")
    assert res.returncode == 0, out(res)[1]
    assert (tmp_path / "py" / "구구단.py").exists()


def test_check_and_words():
    assert pyumsn_cmd("check", EXAMPLES / "안녕.umsn").returncode == 0
    res = pyumsn_cmd("words", "--search", "print")
    assert "엄!" in out(res)[0]
    res = pyumsn_cmd("words", "--translit", "polyfit")
    assert "외_피오르야프이트" in out(res)[0]
    res = pyumsn_cmd("words", "--markdown")
    assert "| `엄슨하다` | `def` |" in out(res)[0]
    assert "PyUMSN" in out(pyumsn_cmd("--version"))[0]


def test_utf8_only(tmp_path):
    bad = tmp_path / "cp949.umsn"
    bad.write_bytes('엄!..하"안녕"..다\n'.encode("cp949"))
    with pytest.raises(UmsnEncodingError):
        read_source(bad)
    res = pyumsn_cmd("run", bad)
    assert res.returncode == 1
    assert "UTF-8" in out(res)[1]

    utf16 = tmp_path / "utf16.umsn"
    utf16.write_bytes('엄!..하"안녕"..다\n'.encode("utf-16"))
    with pytest.raises(UmsnEncodingError):
        read_source(utf16)

    bom = tmp_path / "bom.umsn"
    bom.write_bytes(codecs.BOM_UTF8 + '엄!..하"안녕"..다\n'.encode("utf-8"))
    assert read_source(bom) == '엄!..하"안녕"..다\n'

    cookie = tmp_path / "cookie.py"
    cookie.write_bytes(b"# -*- coding: latin-1 -*-\nx = 1\n")
    with pytest.raises(UmsnEncodingError):
        read_source(cookie)

    out_file = tmp_path / "out.umsn"
    write_source(out_file, "가 ..은 1\n")
    assert not out_file.read_bytes().startswith(codecs.BOM_UTF8)


def test_examples_translate_and_compile():
    for path in sorted(EXAMPLES.glob("*.umsn")):
        compile(umsn_to_py(read_source(path)), str(path), "exec")


def test_ide_is_umsn_and_compiles():
    assert IDE_PATH.suffix == ".umsn"
    src = read_source(IDE_PATH)
    assert pyumsn.check_umsn(src) == []
    py = umsn_to_py(src)
    compile(py, str(IDE_PATH), "exec")
    assert '"엄슨!"' in src  # 실행 단추 이름
    assert "import tkinter as tk" in py
