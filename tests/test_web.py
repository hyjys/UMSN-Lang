"""UMSN-IDE Web: 파이썬 쪽(web/umsn_web.py)과 JS 파일이 저장소와 맞는지 확인한다.

브라우저·Pyodide 없이 도는 부분만 시험한다.
"""

import ast
import json
import re
import sys
from pathlib import Path

import pytest

from pyumsn import write_source

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(WEB))

import umsn_web  # noqa: E402


@pytest.fixture
def work(tmp_path):
    umsn_web.init(str(tmp_path))
    return tmp_path


def test_analyze_spans_and_problems():
    result = json.loads(umsn_web.analyze('엄!..하"안녕"..다\ncount ..은 1\n'))
    cats = {span[0] for span in result["spans"]}
    assert {"bang", "symbol", "string", "error"} <= cats
    (problem,) = result["problems"]
    line, col, length, msg, suggestion = problem
    assert (line, col, length) == (2, 0, 5)
    assert "count" in msg
    assert suggestion == "엄세어"


def test_translate_and_words():
    assert json.loads(umsn_web.to_py('엄!..하"안녕"..다')) == {"ok": True, "code": 'print("안녕")'}
    bad = json.loads(umsn_web.to_py("count ..은 1"))
    assert not bad["ok"] and "count" in bad["error"]
    assert json.loads(umsn_web.to_umsn('print("안녕")', True))["code"] == '엄!("안녕")'
    assert json.loads(umsn_web.translit("polyfit"))["result"] == "외_피오르야프이트"
    assert json.loads(umsn_web.translit("print"))["note"] == "사전 단어"
    assert json.loads(umsn_web.untranslit("외_피오르야프이트"))["result"] == "polyfit"
    assert not json.loads(umsn_web.untranslit("모름"))["ok"]
    assert ["내장 함수·예외", "엄!", "print"] in json.loads(umsn_web.words())


def test_run_program(work, capsys):
    write_source(work / "주.umsn", "엄슨가져와 시스템엄슨\n엄!..하시스템엄슨.인자목록엄슨..엄1..한..슨..다\n")
    assert umsn_web.run_program("주.umsn", '["가", "나 다"]') == 0
    assert "['가', '나 다']" in capsys.readouterr().out

    write_source(work / "끝.umsn", "엄슨가져와 시스템엄슨\n시스템엄슨.엄나가..하3..다\n")
    assert umsn_web.run_program("끝.umsn") == 3

    write_source(work / "오류.umsn", "가 ..은 1\n\n엄!..하가 ..나눠 0..다\n")
    assert umsn_web.run_program("오류.umsn") == 1
    err = capsys.readouterr().err
    assert "line 3" in err and "엄영나누기오류" in err

    write_source(work / "영어.umsn", '엄!..하"실행되면 안 됨"..다\ncount ..은 1\n')
    assert umsn_web.run_program("영어.umsn") == 1
    captured = capsys.readouterr()
    assert "실행되면 안 됨" not in captured.out
    assert "영어.umsn 2줄 1칸" in captured.err


def test_run_program_reloads_edited_modules(work, capsys):
    write_source(work / "값.umsn", "숫자 ..은 1\n")
    write_source(work / "주.umsn", "엄슨가져와 값\n엄!..하값.숫자..다\n")
    assert umsn_web.run_program("주.umsn") == 0
    write_source(work / "값.umsn", "숫자 ..은 2\n")
    assert umsn_web.run_program("주.umsn") == 0
    assert capsys.readouterr().out.split() == ["1", "2"]


def test_changed_files_and_clear(work):
    write_source(work / "주.umsn", '엄슨함께 엄열어..하"결과.txt"..고 "w"..고 엄인코딩방식..은"utf-8"..다 엄으로 파일..한\n    파일.엄써..하"엄슨"..다\n')
    before = umsn_web.snapshot()
    assert umsn_web.run_program("주.umsn") == 0
    assert json.loads(umsn_web.changed_files(before)) == ["결과.txt"]
    assert (work / "결과.txt").read_text(encoding="utf-8") == "엄슨"
    umsn_web.clear_workspace()
    assert list(work.iterdir()) == []


def _relative_imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                names.add(node.module.split(".")[0])
            else:
                names.update(alias.name for alias in node.names)
    return names


# 하위 프로세스를 띄우는 모듈 (함수 안에서만 불러옴). 브라우저에서는 쓰지 않는다.
SUBPROCESS_ONLY = {"cli", "runner", "repl", "__main__"}


def test_worker_module_list_is_complete():
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    listed = set(re.findall(r'"(\w+)"', re.search(r"const PY_MODULES = \[(.*?)\];", worker, re.S).group(1)))
    web_src = (WEB / "umsn_web.py").read_text(encoding="utf-8")
    needed = {"__init__"} | set(re.findall(r"from pyumsn\.(\w+) import", web_src))
    needed |= {n.strip() for n in re.search(r"from pyumsn import ([\w, ]+)", web_src).group(1).split(",")}
    todo = list(needed)
    while todo:
        path = ROOT / "pyumsn" / (todo.pop() + ".py")
        for dep in _relative_imports(path) - SUBPROCESS_ONLY - needed:
            needed.add(dep)
            todo.append(dep)
    assert needed <= listed, needed - listed
    assert not listed & SUBPROCESS_ONLY
    for name in listed:
        assert (ROOT / "pyumsn" / (name + ".py")).exists(), name


def test_examples_menu_matches_examples_dir():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const EXAMPLES = \[(.*?)\n\];", app, re.S).group(1)
    listed = re.findall(r'\["([^"]+)",', block)
    assert sorted(listed) == sorted(p.stem for p in (ROOT / "examples").glob("*.umsn"))


def test_pyodide_version_pinned():
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    assert 'const PYODIDE_VERSION = "314.0.7";' in worker
    assert "d2coding" in worker.lower()
    assert "d2coding" in (WEB / "index.html").read_text(encoding="utf-8").lower()
