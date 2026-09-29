"""UmsnUMSN: PyUMSN 을 ``pyumsn -u pyumsn -o umsnumsn`` 으로 바꾼 엄슨 구현체 (부트스트래핑)."""

from pathlib import Path

from test_cli import EXAMPLES, ROOT, out, pyumsn_cmd

PYUMSN = ROOT / "pyumsn"
UMSNUMSN = ROOT / "umsnumsn"
REGENERATE = "PyUMSN 을 고쳤으면 'pyumsn -u pyumsn -o umsnumsn' 으로 UmsnUMSN 을 다시 만드세요 (지운 파일은 직접 지움)."


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def test_umsnumsn_is_pyumsn_converted_by_cli(tmp_path):
    res = pyumsn_cmd("-uq", PYUMSN, "-o", tmp_path / "umsnumsn")
    assert res.returncode == 0, out(res)[1]
    expected, actual = _files(tmp_path / "umsnumsn"), _files(UMSNUMSN)
    assert sorted(actual) == sorted(expected), REGENERATE
    for rel in expected:
        assert actual[rel] == expected[rel], "%s 가 다르슨. %s" % (rel, REGENERATE)


def test_bootstrap_fixed_point(tmp_path):
    # UmsnUMSN(엄슨)이 자기 자신을 파이썬으로 바꾸면 PyUMSN 과 한 글자도 다르지 않다.
    res = pyumsn_cmd("-m", "umsnumsn", "-tq", UMSNUMSN, "-o", tmp_path / "py", "-x", "ide", cwd=ROOT)
    assert res.returncode == 0, out(res)[1]
    py = _files(tmp_path / "py")
    assert sorted(py) == sorted(rel for rel in _files(PYUMSN) if not rel.startswith("ide/"))
    for rel, data in py.items():
        assert data == (PYUMSN / rel).read_bytes(), rel
    # UmsnUMSN 이 PyUMSN 을 엄슨으로 바꾸면 UmsnUMSN 자신이 나온다.
    res = pyumsn_cmd("-m", "umsnumsn", "-uq", PYUMSN, "-o", tmp_path / "um", cwd=ROOT)
    assert res.returncode == 0, out(res)[1]
    assert _files(tmp_path / "um") == _files(UMSNUMSN)


def test_umsnumsn_runs_and_checks_like_pyumsn(tmp_path):
    res = pyumsn_cmd("-m", "umsnumsn", "-V", cwd=ROOT)
    assert res.returncode == 0 and out(res)[0].startswith("UmsnUMSN (umsnumsn) ")
    for name in ("구구단.umsn", "클래스.umsn"):
        expected = pyumsn_cmd(EXAMPLES / name)
        res = pyumsn_cmd("-m", "umsnumsn", EXAMPLES / name, cwd=ROOT)
        assert res.returncode == 0, out(res)[1]
        assert out(res) == out(expected)
    bad = tmp_path / "나눗셈.umsn"
    bad.write_bytes("엄!..하1 ..나눠 0..다\n".encode("utf-8"))
    expected = pyumsn_cmd(bad)
    res = pyumsn_cmd("-m", "umsnumsn", bad, cwd=ROOT)
    assert res.returncode == expected.returncode == 1
    assert out(res) == out(expected)
    assert "엄영나누기오류" in out(res)[1]
    res = pyumsn_cmd("-m", "umsnumsn", "-c", "엄나가..하3..다", cwd=ROOT)
    assert res.returncode == 3
    res = pyumsn_cmd("-m", "umsnumsn", "-nq", UMSNUMSN, cwd=ROOT)
    assert res.returncode == 0, out(res)[1]


def test_run_module_option(tmp_path):
    res = pyumsn_cmd("-m", "json.tool", "--compact", input_text='{"a": 1}')
    assert res.returncode == 0 and out(res)[0].strip() == '{"a":1}'
    # -m 뒤의 인자는 옵션처럼 보여도 모두 프로그램에 넘어간다
    (tmp_path / "꾸러미").mkdir()
    (tmp_path / "꾸러미" / "__init__.umsn").write_bytes("이름 ..은 '꾸러미'\n".encode("utf-8"))
    (tmp_path / "꾸러미" / "__main__.umsn").write_bytes(
        "엄슨가져와 시스템엄슨\n엄에서 . 엄슨가져와 이름\n엄!..하이름..고 시스템엄슨.인자목록엄슨..엄1..한..슨..다\n"
        .encode("utf-8"))
    res = pyumsn_cmd("--module=꾸러미", "-t", "-x", cwd=tmp_path)
    assert res.returncode == 0, out(res)[1]
    assert out(res)[0].strip() == "꾸러미 ['-t', '-x']"
    res = pyumsn_cmd("-m", "없는모듈")
    assert res.returncode == 1 and "모듈이 없슨: 없는모듈" in out(res)[1]
    res = pyumsn_cmd("-m")
    assert res.returncode == 2
