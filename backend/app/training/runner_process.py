"""Process lifetime and bounded, incremental output reads for the worker."""

import ctypes
import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


if os.name == "nt":
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    _win = ctypes.WinDLL("kernel32", use_last_error=True)
    _win.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _win.CreateJobObjectW.restype = wintypes.HANDLE
    _win.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _win.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _win.OpenProcess.restype = wintypes.HANDLE
    _win.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _win.CloseHandle.argtypes = [wintypes.HANDLE]


def _create_job(process_id: int):
    job = _win.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _win.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        process = _win.OpenProcess(0x0101, False, process_id)  # SET_QUOTA | TERMINATE
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _win.AssignProcessToJobObject(job, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _win.CloseHandle(process)
        return job
    except BaseException:
        _win.CloseHandle(job)
        raise


def command(directory: Path) -> list[str]:
    return [sys.executable, "-B", "-u", "-m", "app.training.runner", str(directory)]


@contextmanager
def worker_file_lock(directory: Path):
    """Keep the CPU slot claimed even if the database connection drops."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".worker.lock").open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                from msvcrt import LK_NBLCK, locking

                locking(stream.fileno(), LK_NBLCK, 1)
            else:
                from fcntl import LOCK_EX, LOCK_NB, flock

                flock(stream.fileno(), LOCK_EX | LOCK_NB)
        except (PermissionError, BlockingIOError):
            yield False
        else:
            yield True  # closing the file releases the lock on both platforms


def child_environment(directory: Path, device_id: str) -> dict[str, str]:
    config_dir = directory / "engine_config"
    config_dir.mkdir(exist_ok=True)
    environment = {**os.environ, "YOLO_OFFLINE": "true",
                   "YOLO_AUTOINSTALL": "false", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                   "YOLO_CONFIG_DIR": str(config_dir), "MPLCONFIGDIR": str(config_dir / "matplotlib")}
    environment.pop("WORKBENCH_DATABASE_URL", None)
    environment.pop("WORKBENCH_TEST_DATABASE_URL", None)
    if device_id == "cpu":
        environment["CUDA_VISIBLE_DEVICES"] = "-1"
    environment.pop("RANK", None)
    environment.pop("LOCAL_RANK", None)
    environment.pop("WORLD_SIZE", None)
    return environment


@contextmanager
def run_child(directory: Path, device_id: str = "cpu"):
    environment = child_environment(directory, device_id)
    with (directory / "training.log").open("ab", buffering=0) as output:
        process = subprocess.Popen(
            command(directory), cwd=Path(__file__).resolve().parents[2], env=environment,
            stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        job = None
        try:
            if os.name == "nt":
                job = _create_job(process.pid)
            assert process.stdin is not None
            process.stdin.write(b"start\n")
            process.stdin.flush()
            yield process
        finally:
            if job:
                _win.CloseHandle(job)
            elif os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=10)


class OutputTail:
    def __init__(self, path: Path, *, progress_lines: bool = False):
        self.path = path
        self.progress_lines = progress_lines
        self.position = 0
        self.pending = b""

    def read(self, *, finished: bool = False) -> list[str]:
        if not self.path.is_file():
            return []
        with self.path.open("rb") as stream:
            stream.seek(self.position)
            chunk = stream.read(256 * 1024)
            self.position = stream.tell()
        data = self.pending + chunk
        if self.progress_lines:
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        lines = data.split(b"\n")
        self.pending = lines.pop()
        if (finished and len(chunk) < 256 * 1024) or len(self.pending) >= 256 * 1024:
            lines.append(self.pending)
            self.pending = b""
        return [line.decode("utf-8", "replace").strip() for line in lines if line.strip()]
