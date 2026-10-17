# -*- coding: utf-8 -*-
"""WP-3 acceptance: the resume Range downloader on a local HTTP server.

* resume after a connection break -> sha256-identical file;
* cancel mid-download -> stops fast, no final file, part files kept;
* a truncated file under the final name is never accepted as ready;
* max_concurrent_downloads=2 with 5 scenes -> at most 2 active.
"""
import hashlib
import http.server
import os
import threading
import time

import pytest

import nisar_qgis.nisar_core.access.download_manager as dm
from nisar_qgis.nisar_core.access.download_manager import (
    DownloadCancelled, DownloadManager, edl_headers,
)
from nisar_qgis.nisar_core.access.b2_asf_search import B2ASFSearchBackend


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"   # one request per connection

    def log_message(self, *args):   # keep pytest output clean
        pass

    def do_HEAD(self):
        srv = self.server.srv
        self.send_response(200)
        self.send_header("Content-Length", str(len(srv.BODY)))
        self.end_headers()

    def do_GET(self):
        srv = self.server.srv
        srv.last_headers = {k.lower(): v
                            for k, v in self.headers.items()}
        total = len(srv.BODY)
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a)
            end = int(b) if b else total - 1
            self.send_response(206)
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, total))
        else:
            start, end = 0, total - 1
            self.send_response(200)
        length = end - start + 1
        self.send_header("Content-Length", str(length))
        self.end_headers()

        limit, srv.drop_after = srv.drop_after, None
        served = 0
        try:
            while served < length:
                chunk = srv.BODY[start + served:start + served + srv.CHUNK]
                if not chunk:
                    break
                if limit is not None and served + len(chunk) > limit:
                    # simulate a connection break mid-stream
                    self.wfile.write(chunk[:limit - served])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                self.wfile.flush()
                served += len(chunk)
                if srv.delay:
                    time.sleep(srv.delay)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True


class _RangeServer:
    """Static-body HTTP server with Range, optional delay/drop."""

    def __init__(self):
        self.BODY = os.urandom(256 * 1024)
        self.digest = hashlib.sha256(self.BODY).digest()
        self.CHUNK = 8192
        self.delay = 0.0
        self.drop_after = None
        self.last_headers = {}
        self._httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _RangeHandler)
        self._httpd.srv = self
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def url(self, name):
        return "http://127.0.0.1:%d/%s" % (
            self._httpd.server_address[1], name)

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture()
def range_server():
    srv = _RangeServer()
    yield srv
    srv.stop()


# ------------------------------------------------------------- acceptance
def test_resume_after_interruption_sha256(tmp_path, range_server):
    range_server.drop_after = 20000     # the first stream dies mid-way
    mgr = DownloadManager({"download_parts": 2, "download_chunk_size": 8192,
                           "request_timeout": 5})
    results, errors = mgr.download_many([{
        "url": range_server.url("g1.h5"), "output_dir": str(tmp_path),
        "expected_size": len(range_server.BODY), "scene_id": "g1"}])
    assert not errors, errors
    out = tmp_path / "g1.h5"
    assert out.stat().st_size == len(range_server.BODY)
    assert hashlib.sha256(out.read_bytes()).digest() == range_server.digest
    # assembly cleaned up: no part/.partial leftovers
    assert [p.name for p in tmp_path.iterdir()] == ["g1.h5"]


def test_cancel_mid_download_fast_no_final(tmp_path, range_server):
    range_server.delay = 0.02
    mgr = DownloadManager({"download_parts": 2, "download_chunk_size": 4096,
                           "request_timeout": 5})
    cancel = threading.Event()
    started = time.monotonic()

    def progress(done, total, status, path):
        if done > 20000:
            cancel.set()

    with pytest.raises(DownloadCancelled):
        mgr.download_scene(
            range_server.url("g2.h5"), str(tmp_path), filename="g2.h5",
            expected_size=len(range_server.BODY),
            cancel_event=cancel, progress_cb=progress)
    assert time.monotonic() - started < 2.0          # TZ: stop within 2 s
    assert not (tmp_path / "g2.h5").exists()         # no final file
    assert not (tmp_path / "g2.h5.partial").exists()
    assert any(p.name.startswith("g2.h5.part")
               for p in tmp_path.iterdir())          # parts kept for resume


def test_truncated_final_file_reredownloaded(tmp_path, range_server):
    final = tmp_path / "t3.h5"
    final.write_bytes(range_server.BODY[:100])       # the old truncation bug
    mgr = DownloadManager({"download_parts": 2, "download_chunk_size": 8192,
                           "request_timeout": 5})
    results, errors = mgr.download_many([{
        "url": range_server.url("t3.h5"), "output_dir": str(tmp_path),
        "expected_size": len(range_server.BODY), "scene_id": "t3"}])
    assert not errors, errors
    assert final.stat().st_size == len(range_server.BODY)
    assert hashlib.sha256(final.read_bytes()).digest() == range_server.digest


def test_max_concurrent_downloads_cap(tmp_path, range_server):
    mgr = DownloadManager({"max_concurrent_downloads": 2,
                           "download_parts": 1, "request_timeout": 5})
    stats = {"n": 0, "max": 0}
    lock = threading.Lock()
    real = mgr.download_scene

    def tracked(*args, **kwargs):
        with lock:
            stats["n"] += 1
            stats["max"] = max(stats["max"], stats["n"])
        try:
            return real(*args, **kwargs)
        finally:
            with lock:
                stats["n"] -= 1

    mgr.download_scene = tracked
    jobs = [{"url": range_server.url("j%d.h5" % i),
             "output_dir": str(tmp_path),
             "expected_size": len(range_server.BODY),
             "scene_id": "j%d" % i} for i in range(5)]
    results, errors = mgr.download_many(jobs)
    assert not errors, errors
    assert len(results) == 5
    assert stats["max"] == 2            # <= max_concurrent_downloads


def test_estimate_total_size_and_free_space(range_server, tmp_path):
    mgr = DownloadManager({"request_timeout": 5})
    total = mgr.estimate_total_size([
        range_server.url("a.h5"), range_server.url("b.h5")])
    assert total == 2 * len(range_server.BODY)
    ok, free = mgr.check_free_space(str(tmp_path), 10)
    assert ok and free > 0
    ok, _ = mgr.check_free_space(str(tmp_path), 10 ** 30)
    assert not ok


def test_user_agent_and_edl_token_header(range_server, monkeypatch):
    monkeypatch.delenv("EDL_TOKEN", raising=False)
    mgr = DownloadManager({"request_timeout": 5, "edl_token": "T0K3N"})
    with mgr._request("GET", range_server.url("a.h5"),
                      stream=True) as response:
        assert response.status_code == 200
    headers = range_server.last_headers
    assert headers["user-agent"].startswith("NISAR-loader/")
    assert headers["authorization"] == "Bearer T0K3N"


def test_edl_headers_env_variable(monkeypatch):
    monkeypatch.delenv("EDL_TOKEN", raising=False)
    assert edl_headers({}) == {}
    monkeypatch.setenv("EDL_TOKEN", " ENVTOKEN ")
    assert edl_headers({}) == {"Authorization": "Bearer ENVTOKEN"}
    assert edl_headers({"edl_token": "CFG"}) == {
        "Authorization": "Bearer CFG"}   # config wins over env


def test_options_covered(range_server, monkeypatch):
    """request_timeout / chunk_size / verify_ssl / proxies reach requests."""
    mgr = DownloadManager({"request_timeout": 7, "download_chunk_size": 4096,
                           "verify_ssl": False, "proxies": {"http": "x"},
                           "download_parts": 1})
    assert mgr.request_timeout[1] == 7
    assert mgr.chunk_size == 4096
    assert mgr.verify_ssl is False
    assert mgr.proxies == {"http": "x"}
    fake_kwargs = {}

    def fake_request(method, url, **kwargs):
        fake_kwargs.update(kwargs)
        import contextlib

        @contextlib.contextmanager
        def ctx():
            class R:
                status_code = 200
                headers = {"Content-Length": "10"}
            yield R()
        return ctx()

    monkeypatch.setattr(dm.requests, "request", fake_request)
    assert mgr.head_size(range_server.url("x.h5")) == 10
    assert fake_kwargs["timeout"] == mgr.request_timeout
    assert fake_kwargs["proxies"] == {"http": "x"}
    assert fake_kwargs["verify"] is False


def test_get_local_path_strict(tmp_path):
    backend = B2ASFSearchBackend({"download_dir": str(tmp_path)})
    scene = type("S", (), {"scene_id": "SCN",
                                                 "size_bytes": 1000})()
    (tmp_path / "SCN.h5").write_bytes(b"0" * 600)    # truncated leftover
    assert backend.get_local_path(scene) is None     # not ready
    (tmp_path / "SCN.h5").write_bytes(b"0" * 1000)
    assert backend.get_local_path(scene) == tmp_path / "SCN.h5"
    # a part/partial file is never returned as the final result
    (tmp_path / "SCN.h5.part0").write_bytes(b"0")
    assert backend.get_local_path(scene) == tmp_path / "SCN.h5"
