"""Suspend-inclusive step deadlines and owned child-group termination."""

import contextlib
import errno
import math
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from functools import lru_cache


POLL_SECONDS = 0.1
TERM_GRACE_SECONDS = 10
KILL_REAP_SECONDS = 10


@lru_cache(maxsize=1)
def _darwin_clock():
    import ctypes

    class Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    libc = ctypes.CDLL(None)
    ticks = libc.mach_continuous_time
    ticks.argtypes = []
    ticks.restype = ctypes.c_uint64
    info = libc.mach_timebase_info
    info.argtypes = [ctypes.POINTER(Timebase)]
    info.restype = ctypes.c_int
    ratio = Timebase()
    if info(ctypes.byref(ratio)) != 0 or not ratio.numer or not ratio.denom:
        raise RuntimeError("UNPROVEN_DEADLINE_CLOCK")
    return lambda: ticks() * ratio.numer // ratio.denom


def continuous_ns():
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    if sys.platform == "darwin":
        return _darwin_clock()()
    raise RuntimeError("UNPROVEN_DEADLINE_CLOCK")


def _sample():
    return time.time_ns(), continuous_ns()


class Deadline:
    def __init__(self, seconds):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("INVALID_STEP_TIMEOUT")
        self.duration = int(seconds * 10**9)
        self.start = self.previous = _sample()
        self.expired = False

    def remaining(self):
        if self.expired:
            return 0
        try:
            current = _sample()
        except (OSError, RuntimeError, AttributeError):
            self.expired = True
            return 0
        if any(a < b for a, b in zip(current, self.previous)):
            self.expired = True
            return 0
        self.previous = current
        left = self.duration - max(a - b for a, b in zip(current, self.start))
        self.expired = left <= 0
        return max(0, left) / 10**9


class DeadlineExpired(RuntimeError):
    pass


class RunDeadline:
    def __init__(self, persist_fence, lock_fd=None):
        self.persist_fence = persist_fence
        self.lock_fd = lock_fd
        self.step = None
        self.current = None

    def fence(self, reason):
        self.persist_fence(f"{self.step}:{reason}")

    def start(self, step, seconds):
        self.check()
        self.step = step
        try:
            self.current = Deadline(seconds)
        except (RuntimeError, OSError, AttributeError):
            self.fence("UNPROVEN_DEADLINE_CLOCK")
            raise
        return self.current

    def check(self):
        if self.current is not None and not self.current.remaining():
            self.fence("STEP_DEADLINE_EXPIRED")
            raise DeadlineExpired("PUBLICATION_FENCED: step deadline expired")


@contextlib.contextmanager
def _exit_observer(pid):
    # Observing exit without reaping retains the group leader's PID until all
    # signals have been sent; a restarted controller never uses a saved PID.
    if hasattr(os, "waitid"):
        yield lambda: os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        return
    with contextlib.closing(select.kqueue()) as queue:
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC, fflags=select.KQ_NOTE_EXIT,
                              flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT)
        done = False

        def exited():
            nonlocal event, done
            if not done:
                try:
                    events = queue.control([event] if event is not None else [], 1, 0)
                except ProcessLookupError:
                    return True
                event = None
                for record in events:
                    if record.flags & select.KQ_EV_ERROR and record.data != errno.ESRCH:
                        raise OSError(record.data, "child exit observer failed")
                    done = True
            return done

        yield exited


def _darwin_group_has_live_process(pgid):
    import ctypes

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    list_group = libproc.proc_listpgrppids
    list_group.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    info = libproc.proc_pidinfo
    info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    pids = (ctypes.c_int * 256)()
    count = list_group(pgid, pids, ctypes.sizeof(pids))
    if count <= 0 or count >= len(pids):
        return True  # Unproven; the unreaped leader should still be listed.
    for pid in pids[:count]:
        # proc_bsdshortinfo: 64 bytes; pid, ppid, pgid, status are the first words.
        fields = (ctypes.c_uint32 * 16)()
        ctypes.set_errno(0)
        size = info(pid, 13, 0, fields, ctypes.sizeof(fields))  # PROC_PIDT_SHORTBSDINFO
        if size == 0 and ctypes.get_errno() == errno.ESRCH:
            continue
        if size != ctypes.sizeof(fields) or fields[0] != pid or fields[2] != pgid or fields[3] != 5:
            return True  # Unknown or not SZOMB.
    return False


def _send_group(child, signum):
    if child.returncode is not None:
        raise RuntimeError("REFUSED_SIGNAL_AFTER_REAP")
    try:
        os.killpg(child.pid, signum)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS can return EPERM for a group containing only unreaped zombies.
        # Do not swallow a real permission failure with a live member.
        if sys.platform == "darwin" and not _darwin_group_has_live_process(child.pid):
            return False
        raise
    return True


def _stop_group(child):
    if _send_group(child, signal.SIGTERM):
        # Cleanup remains possible even if the clock failure caused the fence.
        grace_clock = continuous_ns
        try:
            grace_start = grace_clock()
        except (OSError, RuntimeError, AttributeError):
            grace_clock = time.monotonic_ns
            grace_start = grace_clock()
        while True:
            try:
                elapsed = (grace_clock() - grace_start) / 10**9
            except (OSError, RuntimeError, AttributeError):
                grace_clock = time.monotonic_ns
                grace_start = grace_clock()
                elapsed = 0
            left = TERM_GRACE_SECONDS - elapsed
            if not _send_group(child, 0):
                break
            if left <= 0:
                _send_group(child, signal.SIGKILL)
                break
            time.sleep(min(left, POLL_SECONDS))
    child.wait(timeout=KILL_REAP_SECONDS)


def run_owned(cmd, cwd, env, deadline, fence, lock_fd=None):
    """Fence before signalling. All descendants must stay in the owned group."""
    if not deadline.remaining():
        fence("STEP_DEADLINE_EXPIRED")
        return 124, "TIMEOUT before child start"
    if not hasattr(os, "waitid") and not hasattr(select, "kqueue"):
        fence("UNPROVEN_PROCESS_OBSERVER")
        raise RuntimeError("UNPROVEN_PROCESS_OBSERVER")
    with tempfile.TemporaryFile(dir=cwd) as out, tempfile.TemporaryFile(dir=cwd) as err:
        child = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True,
                                 pass_fds=() if lock_fd is None else (lock_fd,))
        try:
            with _exit_observer(child.pid) as exited:
                while True:
                    left = deadline.remaining()
                    if not left:
                        raise DeadlineExpired("TIMEOUT: step deadline expired")
                    if exited():
                        if not deadline.remaining():
                            raise DeadlineExpired("TIMEOUT: late exit")
                        code = child.wait()
                        break
                    time.sleep(min(left, POLL_SECONDS))
        except DeadlineExpired as exc:
            # governance-mutation: NIGHTLY_DURABLE_FENCE_BEFORE_SIGNAL
            fence("STEP_DEADLINE_EXPIRED")
            _stop_group(child)
            return 124, str(exc)
        except BaseException:
            if child.returncode is None:
                fence("STEP_SUPERVISION_INTERRUPTED")
                _stop_group(child)
            raise
        out.seek(0)
        err.seek(0)
        return code, out.read().decode(errors="replace") + err.read().decode(errors="replace")
