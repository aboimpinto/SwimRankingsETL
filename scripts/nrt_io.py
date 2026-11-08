"""Private durable artifacts and bounded operations for manual NRT trials."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temporary, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'a', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another owned NRT operation is running') from None
        yield


def bounded_call(function, seconds, *args):
    """Linux main-thread bound; no abandoned download threads after a timeout."""
    if seconds <= 0: raise TimeoutError('Operation budget exhausted')
    if signal.getitimer(signal.ITIMER_REAL)[0]: raise RuntimeError('Existing alarm must not be replaced')
    def timeout(*_): raise TimeoutError('Source operation exceeded its time budget')
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try: return function(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, previous)


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
