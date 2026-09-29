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
    res = pyumsn_cmd(EXAMPLES / "안녕.umsn", input_text="엄슨\n")
    stdout, stderr = out(res)
    assert res.returncode == 0, stderr
    assert "안녕, 엄슨!" in stdout
    assert "반가워요, 엄슨님!" in stdout


def test_program_args_after_file(tmp_path):
    prog = tmp_path / "인자.umsn"
    write_source(prog, "엄슨가져와 시스템엄슨\n엄!..하시스템엄슨.인자목록엄슨..엄1..한..슨..다\n")
    res = pyumsn_cmd(prog, "가", "나")
    assert res.returncode == 0, out(res)[1]
    assert "['가', '나']" in out(res)[0]
    # 파일 뒤의 옵션처럼 보이는 인자는 프로그램 몫 (python 과 같음)
    res = pyumsn_cmd(prog, "-t", "--keep", "--", "-x")
    assert "['-t', '--keep', '--', '-x']" in out(res)[0]
    # '--' 뒤는 '-' 로 시작해도 파일
    dash = tmp_path / "-대시.umsn"
    write_source(dash, '엄!..하"대시"..다\n')
    res = pyumsn_cmd("--", dash.name, cwd=tmp_path)
    assert out(res)[0].strip() == "대시"


def test_run_exit_code(tmp_path):
    prog = tmp_path / "끝.umsn"
    write_source(prog, "엄슨가져와 시스템엄슨\n시스템엄슨.엄나가..하3..다\n")
    assert pyumsn_cmd(prog).returncode == 3


def test_run_rejects_english_before_running(tmp_path):
    prog = tmp_path / "영어.umsn"
    write_source(prog, '엄!..하"실행되면 안 됨"..다\ncount ..은 1\n')
    before = temp_files()
    res = pyumsn_cmd(prog)
    stdout, stderr = out(res)
    assert res.returncode == 1
    assert "실행되면 안 됨" not in stdout
    assert "영어 이름 'count'" in stderr
    assert "2줄 1칸" in stderr
    assert temp_files() == before


def test_runtime_error_points_to_umsn_line(tmp_path):
    prog = tmp_path / "오류.umsn"
    write_source(prog, "가 ..은 1\n\n엄!..하가 ..나눠 0..다\n")
    res = pyumsn_cmd(prog)
    stderr = out(res)[1]
    assert res.returncode == 1
    assert 'line 3' in stderr
    assert "엄!..하가 ..나눠 0..다" in stderr
    assert "엄영나누기오류" in stderr


def test_python_syntax_error_reported(tmp_path):
    prog = tmp_path / "문법.umsn"
    write_source(prog, "어엄슨 엄슨참\n    엄!..하1..다\n")
    res = pyumsn_cmd(prog)
    stderr = out(res)[1]
    assert res.returncode == 1
    assert "1줄 8칸" in stderr
    assert "어엄슨 엄슨참" in stderr
    assert "..한" in stderr


def test_temp_file_removed_and_keep():
    before = temp_files()
    assert pyumsn_cmd(EXAMPLES / "구구단.umsn").returncode == 0
    assert temp_files() == before
    res = pyumsn_cmd("--keep", EXAMPLES / "구구단.umsn")
    kept = temp_files() - before
    assert len(kept) == 1
    path = kept.pop()
    assert "def 구구단(단):" in read_source(path)
    os.remove(path)


def test_import_umsn_module(tmp_path):
    write_source(tmp_path / "계산기.umsn", "엄슨하다 더하기..하가..고 나..다..한\n    엄슨한 가 ..더해 나\n")
    write_source(tmp_path / "메인.umsn", "엄슨가져와 계산기\n엄!..하계산기.더하기..하2..고 3..다..다\n")
    res = pyumsn_cmd(tmp_path / "메인.umsn")
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].strip() == "5"


def test_topy_and_toumsn_files(tmp_path):
    src = tmp_path / "hello.py"
    write_source(src, 'def greet(name):\n    return f"hi {name}"\n\nprint(greet("엄슨"))\n')
    assert pyumsn_cmd("-u", src).returncode == 0
    um = read_source(tmp_path / "hello.umsn")
    assert "엄슨하다" in um
    assert pyumsn_cmd("-t", tmp_path / "hello.umsn", "-o", tmp_path / "back.py").returncode == 0
    assert read_source(tmp_path / "back.py") == read_source(src)
    res = pyumsn_cmd(tmp_path / "hello.umsn")
    assert out(res)[0].strip() == "hi 엄슨"


def test_topy_stdout_and_directory(tmp_path):
    res = pyumsn_cmd("-t", EXAMPLES / "구구단.umsn", "-o", "-")
    assert "def 구구단(단):" in out(res)[0]
    res = pyumsn_cmd("-t", EXAMPLES, "-o", tmp_path / "py")
    assert res.returncode == 0, out(res)[1]
    assert (tmp_path / "py" / "구구단.py").exists()


def _make_project(root):
    """패키지·하위 패키지·상대 import·자료 파일·가상 환경이 든 작은 파이썬 프로젝트."""
    files = {
        "main.py": ("import json, os\n"
                    "from app import greet, VERSION\n"
                    "from app.sub.calc import add\n"
                    "print(greet(\"엄슨\"), add(1, 2), VERSION)\n"
                    "with open(os.path.join(os.path.dirname(__file__), \"data\", \"x.json\"),"
                    " encoding=\"utf-8\") as f:\n"
                    "    print(json.load(f)[\"a\"])\n"),
        "app/__init__.py": "from .core import greet\nVERSION = \"1.0\"\n",
        "app/core.py": "def greet(name):\n    return f\"hi {name}\"\n",
        "app/sub/__init__.py": "",
        "app/sub/calc.py": "from .. import VERSION\n\ndef add(a, b):\n    return a + b\n",
        "app/__main__.py": "import core\nprint(core.greet(\"main\"))\n",
        "data/x.json": "{\"a\": 7}\n",
        "README.md": "# 프로젝트\n",
        "tests/test_x.py": "def test_x():\n    assert True\n",
        ".venv/pyvenv.cfg": "home = /usr\n",
        ".venv/lib/junk.py": "x = 1\n",
        ".git/hooks/hook.py": "x = 1\n",
        "app/__pycache__/core.cpython-312.pyc": "",
        "pkg.egg-info/PKG-INFO": "Name: pkg\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        write_source(path, text)
    return files


def _tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_project_to_umsn_and_back(tmp_path):
    src, um, back = tmp_path / "proj", tmp_path / "엄슨", tmp_path / "back"
    files = _make_project(src)
    res = pyumsn_cmd("-u", src, "-o", um)
    assert res.returncode == 0, out(res)[1]
    assert "변환 7개, 복사 2개" in out(res)[1]
    assert _tree(um) == ["README.md", "app/__init__.umsn", "app/__main__.umsn", "app/core.umsn",
                         "app/sub/__init__.umsn", "app/sub/calc.umsn", "data/x.json", "main.umsn",
                         "tests/test_x.umsn"]
    # 변환된 엄슨 프로젝트가 그대로 실행된다 (패키지 __init__.umsn, 상대 import, 자료 파일)
    res = pyumsn_cmd(um / "main.umsn")
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].split() == ["hi", "엄슨", "3", "1.0", "7"]
    # 폴더를 주면 __main__.umsn 을 실행 (python 폴더/ 처럼)
    res = pyumsn_cmd(um / "app")
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].strip() == "hi main"
    # 되돌리면 원래 프로젝트와 똑같다 (건너뛴 폴더 빼고)
    res = pyumsn_cmd("-tq", um, "-o", back)
    assert res.returncode == 0 and out(res) == ("", "")
    expected = sorted(rel for rel in files if not rel.startswith((".venv", ".git", "pkg.egg-info"))
                      and "__pycache__" not in rel)
    assert _tree(back) == expected
    for rel in expected:
        assert (back / rel).read_bytes() == (src / rel).read_bytes(), rel


def test_project_exclude_no_copy_and_nested_output(tmp_path):
    src = tmp_path / "proj"
    _make_project(src)
    # 출력 폴더가 원본 안에 있어도 되고, 다시 실행해도 출력 폴더는 변환하지 않는다
    for _ in range(2):
        res = pyumsn_cmd("-u", src, "-o", src / "엄슨", "-x", "tests", "--no-copy")
        assert res.returncode == 0, out(res)[1]
    assert _tree(src / "엄슨") == ["app/__init__.umsn", "app/__main__.umsn", "app/core.umsn",
                                  "app/sub/__init__.umsn", "app/sub/calc.umsn", "main.umsn"]
    # 제자리 변환: 파일 옆에 만들고 아무것도 복사하지 않는다
    res = pyumsn_cmd("-uq", src, "-x", "엄슨", "-x", "app/sub")
    assert res.returncode == 0, out(res)[1]
    assert (src / "app" / "core.umsn").exists() and (src / "tests" / "test_x.umsn").exists()
    assert not (src / "app" / "sub" / "calc.umsn").exists()
    assert not (src / ".venv" / "lib" / "junk.umsn").exists()
    # 검사도 같은 규칙으로 폴더를 훑는다
    res = pyumsn_cmd("-n", src, "-x", "tests")
    assert res.returncode == 0, out(res)[1]
    checked = out(res)[0]
    assert "calc.umsn" in checked and "test_x" not in checked and "junk" not in checked


def test_project_topy_skips_clashing_copies(tmp_path):
    src = tmp_path / "um"
    src.mkdir()
    write_source(src / "a.umsn", "엄!..하1..다\n")
    write_source(src / "a.py", "print(2)\n")
    write_source(src / "b.py", "print(3)\n")
    res = pyumsn_cmd("-t", src, "-o", tmp_path / "py")
    assert res.returncode == 0, out(res)[1]
    assert "복사하지 않았슨" in out(res)[1]
    assert read_source(tmp_path / "py" / "a.py") == "print(1)\n"
    assert read_source(tmp_path / "py" / "b.py") == "print(3)\n"


def test_import_hook_prefers_py_and_finds_umsn_packages(tmp_path):
    write_source(tmp_path / "둘.py", "값 = 'py'\n")
    write_source(tmp_path / "둘.umsn", "값 ..은 '엄슨'\n")
    (tmp_path / "꾸러미").mkdir()
    write_source(tmp_path / "꾸러미" / "__init__.umsn", "값 ..은 '꾸러미'\n")
    write_source(tmp_path / "메인.umsn",
                 "엄슨가져와 둘..고 꾸러미\n엄!..하둘.값..고 꾸러미.값..다\n")
    res = pyumsn_cmd(tmp_path / "메인.umsn")
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].split() == ["py", "꾸러미"]


def test_check_and_words():
    assert pyumsn_cmd("-n", EXAMPLES / "안녕.umsn").returncode == 0
    res = pyumsn_cmd("-w", "print")
    assert "엄!" in out(res)[0]
    res = pyumsn_cmd("--translit", "polyfit")
    assert "외_피오르야프이트" in out(res)[0]
    res = pyumsn_cmd("--untranslit", "외_피오르야프이트", "엄!")
    assert "polyfit" in out(res)[0] and "print" in out(res)[0]
    res = pyumsn_cmd("-M")
    assert "| `엄슨하다` | `def` |" in out(res)[0]
    assert "PyUMSN" in out(pyumsn_cmd("--version"))[0]


def test_utf8_only(tmp_path):
    bad = tmp_path / "cp949.umsn"
    bad.write_bytes('엄!..하"안녕"..다\n'.encode("cp949"))
    with pytest.raises(UmsnEncodingError):
        read_source(bad)
    res = pyumsn_cmd(bad)
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


def test_stdin_and_command():
    res = pyumsn_cmd(input_text='엄!..하"표준 입력"..다\n')
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].strip() == "표준 입력"
    code = "엄슨가져와 시스템엄슨\n엄!..하시스템엄슨.인자목록엄슨..다\n"
    res = pyumsn_cmd("-", "가", input_text=code)
    assert out(res)[0].strip() == "['-', '가']"
    res = pyumsn_cmd("-c", code, "가", "-k")
    assert out(res)[0].strip() == "['-c', '가', '-k']"
    before = temp_files()
    res = pyumsn_cmd("-c", "가 ..은 1\n엄!..하가 ..나눠 0..다")
    stderr = out(res)[1]
    assert res.returncode == 1
    assert 'File "<string>", line 2' in stderr
    assert "엄!..하가 ..나눠 0..다" in stderr
    assert temp_files() == before
    assert not glob.glob(os.path.join(tempfile.gettempdir(), "umsn_*.umsn"))


def test_filters_stdin_to_stdout():
    res = pyumsn_cmd("-t", input_text='엄!..하"안녕"..다\n')
    assert out(res)[0] == 'print("안녕")\n'
    res = pyumsn_cmd("-u", "-", input_text='print("안녕")\n')
    assert out(res)[0] == '엄!..하"안녕"..다\n'
    res = pyumsn_cmd("-ua", input_text='print("안녕")\n')
    assert out(res)[0] == '엄!("안녕")\n'
    res = pyumsn_cmd("-n", input_text="count ..은 1\n")
    assert res.returncode == 1
    assert "<stdin> 1줄 1칸" in out(res)[1]


def test_options_after_operands_and_bundling(tmp_path):
    # 변환 모드에서는 옵션이 파일 뒤에 와도 된다 (GNU 방식)
    res = pyumsn_cmd("-t", EXAMPLES / "안녕.umsn", "--output", tmp_path / "a.py")
    assert res.returncode == 0, out(res)[1]
    assert "만들었슨" in out(res)[1]
    res = pyumsn_cmd("-tq", EXAMPLES / "안녕.umsn", EXAMPLES / "구구단.umsn", "-o", tmp_path / "많이")
    assert res.returncode == 0
    assert out(res)[1] == ""
    assert (tmp_path / "많이" / "안녕.py").exists() and (tmp_path / "많이" / "구구단.py").exists()
    res = pyumsn_cmd("-t", EXAMPLES / "안녕.umsn", "-o" + str(tmp_path / "붙임.py"), "--qui")
    assert res.returncode == 0 and (tmp_path / "붙임.py").exists()
    res = pyumsn_cmd("-nq", EXAMPLES)
    assert res.returncode == 0 and out(res) == ("", "")


def test_usage_errors():
    cases = [
        (["-z"], "알 수 없는 옵션 -- 'z'"),
        (["-x"], "값이 필요하슨"),
        (["-x", "a", "a.umsn"], "'-x'"),
        (["--no-copy", "-n", "a.umsn"], "'--no-copy'"),
        (["--nope"], "알 수 없는 옵션 '--nope'"),
        (["-o"], "값이 필요하슨"),
        (["--to", "a.umsn"], "헷갈리슨"),
        (["-t", "-u"], "함께 쓸 수 없슨"),
        (["-k", "-t", "a.umsn"], "'-k'"),
        (["-o", "x", "a.umsn"], "'-o'"),
        (["-i", "a.umsn"], "'-i'"),
        (["--translit"], "바꿀 이름"),
        (["topy", "a.umsn"], "pyumsn -t"),
    ]
    for argv, message in cases:
        res = pyumsn_cmd(*argv)
        stderr = out(res)[1]
        assert res.returncode == 2, (argv, stderr)
        assert stderr.startswith("pyumsn: "), stderr
        assert message in stderr, (argv, stderr)
        assert "pyumsn --help" in stderr
    res = pyumsn_cmd("-h")
    assert res.returncode == 0
    assert out(res)[0].startswith("사용법: pyumsn")


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
