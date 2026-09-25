import hashlib
import http.server
import threading

import pytest

from charpente.core import download
from charpente.errors import ChError

PAYLOAD = bytes(range(256)) * 400          # ~100 KB


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = PAYLOAD
    cut_after = None                       # close the connection after this many bytes (once)
    ignore_range = False
    requests: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        cls = type(self)
        start = 0
        rng = self.headers.get("Range")
        cls.requests.append(rng)
        if rng and not cls.ignore_range:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(cls.payload):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
        else:
            self.send_response(200)
        body = cls.payload[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if cls.cut_after is not None:
            limit, cls.cut_after = cls.cut_after, None
            self.wfile.write(body[:limit])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


@pytest.fixture
def server():
    _Handler.payload = PAYLOAD
    _Handler.cut_after = None
    _Handler.ignore_range = False
    _Handler.requests = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/file.bin"
    httpd.shutdown()
    httpd.server_close()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_download_and_verify(server, tmp_path):
    dest = tmp_path / "out" / "file.bin"
    seen = []
    result = download.download(server, dest, sha256=sha(PAYLOAD), progress=lambda a, b: seen.append((a, b)))
    assert result == dest and dest.read_bytes() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert not (tmp_path / "out" / "file.bin.part").exists()


def test_an_interrupted_transfer_resumes_instead_of_restarting(server, tmp_path):
    _Handler.cut_after = 30000
    dest = tmp_path / "file.bin"
    download.download(server, dest, sha256=sha(PAYLOAD), backoff=0)
    assert dest.read_bytes() == PAYLOAD
    assert _Handler.requests[0] is None                       # first attempt: whole file
    assert _Handler.requests[1] == "bytes=30000-"             # second: only the missing part


def test_a_server_that_ignores_range_restarts_cleanly(server, tmp_path):
    part = tmp_path / "file.bin.part"
    part.write_bytes(PAYLOAD[:5000])
    _Handler.ignore_range = True
    download.download(server, tmp_path / "file.bin", sha256=sha(PAYLOAD))
    assert (tmp_path / "file.bin").read_bytes() == PAYLOAD


def test_existing_complete_part_file_is_accepted_on_416(server, tmp_path):
    (tmp_path / "file.bin.part").write_bytes(PAYLOAD)
    download.download(server, tmp_path / "file.bin", sha256=sha(PAYLOAD))
    assert (tmp_path / "file.bin").read_bytes() == PAYLOAD


def test_checksum_mismatch_discards_the_file(server, tmp_path):
    with pytest.raises(ChError) as exc:
        download.download(server, tmp_path / "file.bin", sha256="0" * 64)
    assert exc.value.code == "CH6002"
    assert not (tmp_path / "file.bin").exists() and not (tmp_path / "file.bin.part").exists()


def test_budget_refuses_before_downloading(server, tmp_path):
    with pytest.raises(ChError) as exc:
        download.download(server, tmp_path / "file.bin", max_bytes=1000)
    assert exc.value.code == "CH6003"
    assert not (tmp_path / "file.bin").exists()


def test_unreachable_server_is_a_coded_error(tmp_path):
    with pytest.raises(ChError) as exc:
        download.download("http://127.0.0.1:1/x", tmp_path / "f", retries=1, backoff=0, timeout=1)
    assert exc.value.code == "CH6001"


def test_file_urls_work_and_are_verified(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"local data")
    dest = download.download(src.as_uri(), tmp_path / "copy.bin", sha256=sha(b"local data"))
    assert dest.read_bytes() == b"local data"


def test_offline_mode_refuses_the_network_but_not_local_files(server, tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_OFFLINE", "1")
    with pytest.raises(ChError) as exc:
        download.download(server, tmp_path / "f")
    assert exc.value.code == "CH6004"
    (tmp_path / "s").write_bytes(b"x")
    download.download((tmp_path / "s").as_uri(), tmp_path / "d")


def test_unsupported_scheme(tmp_path):
    with pytest.raises(ChError) as exc:
        download.download("ftp://example.com/x", tmp_path / "f")
    assert exc.value.code == "CH6001"
