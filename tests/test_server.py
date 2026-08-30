import os
import socket
import tempfile
import threading
import pytest
from unittest.mock import patch, MagicMock

from select_to_speech.api.server import is_server_running, run_server


def test_is_server_running_nonexistent():
    assert not is_server_running("/tmp/nonexistent_select_to_speech_test.sock")


def test_is_server_running_stale_socket(tmp_path):
    sock_path = str(tmp_path / "stale.sock")
    # Create a socket file and immediately close it so nothing listens on it
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(sock_path)
    s.close()
    
    assert not is_server_running(sock_path)


def test_is_server_running_active(tmp_path):
    sock_path = str(tmp_path / "active.sock")
    server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_sock.bind(sock_path)
    server_sock.listen(1)

    def handle_client():
        try:
            conn, _ = server_sock.accept()
            req = conn.recv(1024)
            if b"GET /status" in req:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\n{\"status\":\"ok\"}")
            conn.close()
        except Exception:
            pass

    t = threading.Thread(target=handle_client, daemon=True)
    t.start()

    try:
        assert is_server_running(sock_path) is True
    finally:
        server_sock.close()


def test_run_server_already_running():
    with patch("select_to_speech.api.server.is_server_running", return_value=True):
        res = run_server()
        assert res == 0
