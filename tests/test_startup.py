"""Exercise the deployment path using Alembic, a real server and a fresh DB."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def test_migrated_database_and_real_server(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, DATABASE_URL='sqlite:///' + (tmp_path / 'startup.db').as_posix(),
               AION_REQUIRE_A2A='1', AION_DISABLE_EXTERNAL_DISCOVERY='1')
    for command in [('upgrade', 'head'), ('upgrade', 'head'), ('check',)]:
        subprocess.run([sys.executable, '-m', 'alembic', *command], cwd=root,
                       env=env, check=True, capture_output=True, text=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with (tmp_path / 'server.log').open('w+') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                                    '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=root, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise AssertionError(log.read())
                    time.sleep(0.1)
            assert health['version'] == '0.7.1'
            assert health['a2a_runtime'] == 'mounted'
            with urlopen(f'http://127.0.0.1:{port}/stats', timeout=3) as response:
                assert json.load(response)['agents_raw_rows'] == 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
