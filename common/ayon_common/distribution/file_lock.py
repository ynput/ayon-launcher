"""Lock file that works between processes and between machines.

Used to make sure only one process distributes an item (addon, dependency
package, launcher version) into a storage folder, which may be shared by
many machines, e.g. 'AYON_LAUNCHER_STORAGE_DIR' on a network share.

How it works:
- The lock is a file created with 'O_EXCL', so only one process can create
    it, also on network file systems (SMB, NFSv3+).
- The owner rewrites the file content every few seconds (heartbeat).
- Other processes wait while the content keeps changing. When it does not
    change for 'stale timeout' seconds, measured with the waiting process'
    own clock, the owner is considered dead and the lock is taken over.
    Clock differences between machines do not matter, and reading the
    content (not only the modification time) also works on NFS with
    attribute caching.
- If the owner runs on the same machine and its process is gone, the lock
    is taken over immediately.

The lock only prevents duplicate work. Callers must still write results
in a way that is safe without it (e.g. rename a finished folder into place),
because a lock can be taken over from a process that was paused for longer
than the stale timeout, and waiting gives up after the wait timeout.
"""

import os
import json
import time
import uuid
import random
import socket
import logging
import platform
import threading
from typing import Optional, Generator

LOCK_STALE_TIMEOUT_ENV = "AYON_LAUNCHER_DIST_LOCK_STALE_TIMEOUT"
LOCK_WAIT_TIMEOUT_ENV = "AYON_LAUNCHER_DIST_LOCK_WAIT_TIMEOUT"
DEFAULT_LOCK_STALE_TIMEOUT = 120.0
DEFAULT_LOCK_WAIT_TIMEOUT = 3600.0
# Seconds between checks of a lock held by another process (+ jitter)
LOCK_POLL_INTERVAL = 1.0
# Give up when creating the lock keeps failing with permission errors.
#   On Windows a lock file that is being removed by its owner raises
#   'PermissionError' for a moment, so a few failures are expected.
_MAX_PERMISSION_ERRORS = 30
IS_WINDOWS = platform.system().lower() == "windows"
_O_BINARY = getattr(os, "O_BINARY", 0)

log = logging.getLogger(__name__)


def _env_seconds(env_name: str, default: float) -> float:
    value = os.getenv(env_name)
    if not value:
        return default
    try:
        seconds = float(value)
    except ValueError:
        seconds = -1.0
    if seconds <= 0:
        log.warning(
            f"Invalid value '{value}' of '{env_name}'."
            f" Using default {default}s."
        )
        return default
    return seconds


def get_lock_stale_timeout() -> float:
    """Seconds without heartbeat after which a lock is abandoned.

    Can be changed with 'AYON_LAUNCHER_DIST_LOCK_STALE_TIMEOUT'.

    Returns:
        float: Stale timeout in seconds.

    """
    return _env_seconds(LOCK_STALE_TIMEOUT_ENV, DEFAULT_LOCK_STALE_TIMEOUT)


def get_lock_wait_timeout() -> float:
    """Max seconds to wait for a lock that is held by another process.

    Can be changed with 'AYON_LAUNCHER_DIST_LOCK_WAIT_TIMEOUT'.

    Returns:
        float: Wait timeout in seconds.

    """
    return _env_seconds(LOCK_WAIT_TIMEOUT_ENV, DEFAULT_LOCK_WAIT_TIMEOUT)


def _get_pid_namespace() -> Optional[str]:
    """Linux PID namespace, PIDs can be compared only in the same one."""
    try:
        return os.readlink("/proc/self/ns/pid")
    except (OSError, AttributeError):
        return None


def _is_process_running(pid: int) -> bool:
    """Process with given PID is running on this machine.

    Returns True when it can't be determined.
    """
    if pid <= 0:
        return True

    if IS_WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            # Access denied means the process exists
            return ctypes.GetLastError() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            ):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # e.g. PermissionError -> process exists but is owned by other user
        return True
    return True


class _Unreadable:
    """Lock content that could not be read (e.g. file is being removed)."""


class DistributionLock:
    """Lock file for distribution of a single item.

    Example:
        >>> lock = DistributionLock("/storage/addons/.dist_locks/core.lock")
        >>> for acquired in lock.acquire_iter():
        ...     if acquired is None:
        ...         continue  # still waiting, do something else
        ...     break
        >>> try:
        ...     ...  # distribute if 'acquired' is True
        ... finally:
        ...     lock.release()

    Args:
        path (str): Path to the lock file. Parent folder is created.
        stale_timeout (Optional[float]): Seconds without heartbeat after
            which the lock is considered abandoned. Defaults to
            'AYON_LAUNCHER_DIST_LOCK_STALE_TIMEOUT' or 120.
        wait_timeout (Optional[float]): Max seconds to wait for the lock.
            Defaults to 'AYON_LAUNCHER_DIST_LOCK_WAIT_TIMEOUT' or 3600.
        poll_interval (Optional[float]): Seconds between checks while
            waiting. Random jitter is added so many machines don't check
            at the same moment.
        logger (Optional[logging.Logger]): Logger.

    """
    def __init__(
        self,
        path: str,
        stale_timeout: Optional[float] = None,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        logger: Optional[logging.Logger] = None,
    ):
        if stale_timeout is None:
            stale_timeout = get_lock_stale_timeout()
        if wait_timeout is None:
            wait_timeout = get_lock_wait_timeout()
        if poll_interval is None:
            poll_interval = LOCK_POLL_INTERVAL
        self.path: str = path
        self.log: logging.Logger = logger or log
        self._stale_timeout: float = stale_timeout
        self._wait_timeout: float = wait_timeout
        # Poll at least a few times within stale timeout
        self._poll_interval: float = min(poll_interval, stale_timeout / 4)
        # Heartbeat often enough that waiters see changes well within
        #   stale timeout, but don't hammer the file server.
        self._heartbeat_interval: float = max(
            0.05, min(10.0, stale_timeout / 8)
        )

        self._token: str = uuid.uuid4().hex
        self._hostname: str = socket.gethostname()
        self._pid_namespace: Optional[str] = _get_pid_namespace()
        self._owned: bool = False
        self._lost: bool = False
        self._beat: int = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def owned(self) -> bool:
        """This object currently holds the lock."""
        return self._owned

    @property
    def lost(self) -> bool:
        """Lock was taken over by another process while it was held.

        That happens only when this process did not refresh the lock for
        longer than stale timeout (e.g. the machine was suspended).
        """
        return self._lost

    def try_acquire(self) -> bool:
        """Try to create the lock file without waiting.

        Returns:
            bool: Lock was acquired.

        Raises:
            PermissionError: Lock file can't be created right now.
            OSError: Lock directory can't be created.

        """
        if self._owned:
            return True

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY,
                0o666,
            )
        except FileExistsError:
            return False

        try:
            os.write(fd, self._get_content())
        finally:
            os.close(fd)

        self._owned = True
        self._lost = False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"DistributionLock {os.path.basename(self.path)}",
            daemon=True,
        )
        self._thread.start()
        return True

    def acquire_iter(
        self, wait_timeout: Optional[float] = None
    ) -> Generator[Optional[bool], None, None]:
        """Acquire the lock, waiting for other process if needed.

        Generator does not block. It yields 'None' while waiting so the
        caller can do other work, then yields 'True' when the lock was
        acquired or 'False' when it gave up (wait timeout, or the lock
        can't be created at all).

        Args:
            wait_timeout (Optional[float]): Override wait timeout.

        Returns:
            Generator[Optional[bool], None, None]: None while waiting,
                then True or False.

        """
        if wait_timeout is None:
            wait_timeout = self._wait_timeout

        started = time.monotonic()
        next_check = started
        last_content = None
        last_change = started
        permission_errors = 0
        logged_wait = False
        while True:
            now = time.monotonic()
            if now < next_check:
                yield None
                continue

            try:
                if self.try_acquire():
                    if logged_wait:
                        self.log.debug(
                            f"Acquired lock {self.path} after"
                            f" {now - started:.1f}s"
                        )
                    yield True
                    return
                permission_errors = 0

            except PermissionError:
                permission_errors += 1
                if permission_errors >= _MAX_PERMISSION_ERRORS:
                    self.log.warning(
                        f"Can't create lock file {self.path}."
                        " Continuing without lock.",
                        exc_info=True,
                    )
                    yield False
                    return
                next_check = now + 0.1 + random.random() * 0.2
                yield None
                continue

            except OSError:
                self.log.warning(
                    f"Can't create lock file {self.path}."
                    " Continuing without lock.",
                    exc_info=True,
                )
                yield False
                return

            content = self._read_content(self.path)
            if content is None:
                # Released in the meantime, try again soon
                last_content = None
                next_check = now + random.random() * 0.2
                yield None
                continue

            if not logged_wait:
                logged_wait = True
                self.log.info(
                    "Waiting for other process to finish"
                    f" ({self._describe_owner(content)}), lock {self.path}"
                )

            if self._owner_is_dead(content):
                self.log.info(
                    f"Owner of lock {self.path} is not running anymore."
                )
                self._break_stale_lock(content)
                next_check = now
                continue

            if (
                isinstance(content, _Unreadable)
                or content != last_content
            ):
                last_content = content
                last_change = now

            elif (now - last_change) >= self._stale_timeout:
                self.log.info(
                    f"Lock {self.path} was not refreshed for"
                    f" {now - last_change:.0f}s. Taking it over."
                )
                self._break_stale_lock(content)
                last_content = None
                last_change = now
                next_check = now
                continue

            if (now - started) >= wait_timeout:
                self.log.warning(
                    f"Waited {now - started:.0f}s for lock {self.path}."
                    " Continuing without lock."
                )
                yield False
                return

            next_check = now + self._poll_interval * (
                0.5 + random.random()
            )
            yield None

    def acquire(self, wait_timeout: Optional[float] = None) -> bool:
        """Blocking variant of 'acquire_iter'.

        Args:
            wait_timeout (Optional[float]): Override wait timeout.

        Returns:
            bool: Lock was acquired.

        """
        for result in self.acquire_iter(wait_timeout):
            if result is not None:
                return result
            time.sleep(0.05)
        return False

    def release(self):
        """Release the lock if it is held by this object."""
        if not self._owned:
            return

        self._owned = False
        self._stop_event.set()
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
        ):
            self._thread.join()
        self._thread = None

        if self._lost or not self._is_own_lock():
            return

        # On Windows the file can't be removed while another process has
        #   it open for reading, which is only for a moment.
        for _ in range(50):
            try:
                os.remove(self.path)
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.05)
            except OSError:
                break
        self.log.warning(
            f"Failed to remove lock file {self.path}. Other processes will"
            f" take it over after {self._stale_timeout:.0f}s."
        )

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.release()

    # --- Internal ---
    def _get_content(self) -> bytes:
        return json.dumps({
            "token": self._token,
            "hostname": self._hostname,
            "pid": os.getpid(),
            "pid_namespace": self._pid_namespace,
            "beat": self._beat,
            "time": time.time(),
        }).encode("utf-8")

    @staticmethod
    def _read_content(path: str):
        """Read lock content.

        Returns:
            Union[bytes, _Unreadable, None]: Content, '_Unreadable' if it
                could not be read, None if the file does not exist.

        """
        try:
            with open(path, "rb") as stream:
                return stream.read()
        except FileNotFoundError:
            return None
        except OSError:
            # Windows: file is being removed
            return _Unreadable()

    @staticmethod
    def _parse_content(content) -> dict:
        if not isinstance(content, bytes):
            return {}
        try:
            data = json.loads(content.decode("utf-8"))
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _describe_owner(self, content) -> str:
        data = self._parse_content(content)
        if not data:
            return "unknown owner"
        return f"{data.get('hostname')} pid {data.get('pid')}"

    def _owner_is_dead(self, content) -> bool:
        """Owner of the lock is a process on this machine that is gone."""
        data = self._parse_content(content)
        if not data or data.get("token") == self._token:
            return False
        if (
            data.get("hostname") != self._hostname
            or data.get("pid_namespace") != self._pid_namespace
        ):
            return False
        pid = data.get("pid")
        if not isinstance(pid, int) or pid == os.getpid():
            return False
        return not _is_process_running(pid)

    def _is_own_lock(self) -> bool:
        data = self._parse_content(self._read_content(self.path))
        return data.get("token") == self._token

    def _break_stale_lock(self, stale_content):
        """Remove lock file that was found to be stale.

        Rename is atomic, so when multiple processes find the same stale
        lock only one of them removes it.
        """
        if self._read_content(self.path) != stale_content:
            return
        stale_path = f"{self.path}.{uuid.uuid4().hex}.stale"
        try:
            os.rename(self.path, stale_path)
        except OSError:
            return
        try:
            os.remove(stale_path)
        except OSError:
            pass

    def _heartbeat_loop(self):
        while not self._stop_event.wait(self._heartbeat_interval):
            if not self._is_own_lock():
                self._lost = True
                self.log.warning(
                    f"Lock {self.path} was taken over by other process."
                )
                return
            self._beat += 1
            try:
                # No 'O_CREAT' so a lock removed by other process is not
                #   created again
                fd = os.open(self.path, os.O_WRONLY | os.O_TRUNC | _O_BINARY)
            except OSError:
                # Try again with next beat
                continue
            try:
                os.write(fd, self._get_content())
            except OSError:
                pass
            finally:
                os.close(fd)
