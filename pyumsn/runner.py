"""엄슨 파일 실행기: 임시 파이썬 파일을 만들어 하위 프로세스로 실행한다."""

import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .sourceio import read_source, write_source
from .translator import umsn_to_py

_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)


KEEP_ENV = "PYUMSN_KEEP_TEMP"


def child_env(keep=False):
    """하위 프로세스 환경: UTF-8 강제 + pyumsn 을 찾을 수 있게.

    keep 이 거짓이면 launcher 가 임시 .py 를 읽자마자 지운다.
    """
    env = os.environ.copy()
    if keep:
        env[KEEP_ENV] = "1"
    else:
        env.pop(KEEP_ENV, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = _PACKAGE_PARENT + (os.pathsep + old if old else "")
    return env


def build_command(py_path, umsn_path, args=(), unbuffered=False):
    """임시 .py 를 원본 .umsn 이름으로 실행하는 명령줄."""
    cmd = [sys.executable, "-X", "utf8"]
    if unbuffered:
        cmd.append("-u")
    cmd += ["-m", "pyumsn.launcher", str(py_path), str(umsn_path)]
    cmd += [str(a) for a in args]
    return cmd


def make_temp_py(py_source):
    """UTF-8 임시 파이썬 파일을 만들고 경로를 돌려준다 (윈도우 잠금을 피하려고 바로 닫음)."""
    fd, tmp = tempfile.mkstemp(prefix="umsn_", suffix=".py")
    os.close(fd)
    write_source(tmp, py_source)
    return tmp


def prepare(umsn_path):
    """엄슨 파일을 변환해 임시 .py 를 만든다. 문법 오류면 파일을 만들지 않고 예외."""
    umsn_path = Path(umsn_path)
    source = read_source(umsn_path)
    py = umsn_to_py(source, filename=str(umsn_path))
    return make_temp_py(py)


def remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _catch_sigterm():
    """SIGTERM 을 SystemExit 로 바꿔 finally 정리(임시 파일 삭제)가 되게 한다."""
    if not hasattr(signal, "SIGTERM"):
        return None
    def handler(signum, frame):
        raise SystemExit(128 + signum)
    try:
        return signal.signal(signal.SIGTERM, handler)
    except ValueError:  # 메인 스레드가 아님
        return None


def _restore_sigterm(old):
    if old is not None:
        try:
            signal.signal(signal.SIGTERM, old)
        except ValueError:
            pass


def run_file(path, args=(), keep=False, show_py=False):
    """엄슨 파일을 실행하고 종료 코드를 돌려준다."""
    path = Path(path).resolve()
    tmp = prepare(path)
    old_handler = _catch_sigterm()
    try:
        if show_py:
            sys.stderr.write("---- 변환된 파이썬 (%s) ----\n" % tmp)
            sys.stderr.write(read_source(tmp))
            sys.stderr.write("\n---- 실행 ----\n")
            sys.stderr.flush()
        elif keep:
            sys.stderr.write("임시 파이썬 파일: %s\n" % tmp)
            sys.stderr.flush()
        proc = subprocess.Popen(build_command(tmp, path, args), env=child_env(keep))
        try:
            return proc.wait()
        except KeyboardInterrupt:
            try:
                return proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                proc.kill()
                return 130
        except SystemExit:
            proc.terminate()
            raise
    finally:
        _restore_sigterm(old_handler)
        if not keep:
            remove_quietly(tmp)
