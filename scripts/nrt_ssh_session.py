"""An operation-owned SSH connection; cleanup never targets another session."""
from contextlib import contextmanager
from pathlib import Path
import re
import subprocess
import tempfile
import time


@contextmanager
def ssh_session(host):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
        raise ValueError('Invalid SSH alias')
    with tempfile.TemporaryDirectory(prefix='nrt-ssh-') as directory:
        socket = str(Path(directory) / 'control')
        process = subprocess.Popen(['ssh', '-M', '-S', socket, '-N', '-o', 'BatchMode=yes',
                                    '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
                                    '-o', 'ServerAliveCountMax=3', host],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 12
            while not Path(socket).exists():
                if process.poll() is not None: raise RuntimeError('Owned SSH connection failed to start')
                if time.monotonic() >= deadline: raise TimeoutError('Owned SSH socket startup timed out')
                time.sleep(0.05)
            subprocess.run(['ssh', '-S', socket, '-O', 'check', host], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            yield socket
        finally:
            if process.poll() is None:
                try:
                    subprocess.run(['ssh', '-S', socket, '-O', 'exit', host],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    process.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            if process.stderr: process.stderr.close()
