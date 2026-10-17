# -*- coding: utf-8 -*-
"""WP-3: resume-capable parallel Range download manager (core, no QGIS).

Based on the field-proven scheme of validation/windthrow_new_sites/
nisar_dl.py (validated on real GUNW granule downloads, 2026):

* the granule is fetched as N parallel HTTP Range parts, each streamed
  to ``<name>.part<i>`` and resumed by appending after any interruption;
* the parts are stitched into ``<name>.partial``, verified by size and
  only then atomically renamed (``os.replace``) to the final name - a
  truncated file under the FINAL name (the old bug) is never accepted
  as ready;
* cancellation through a ``threading.Event`` checked on every block:
  the final file does not appear, the part files stay for a later
  resume;
* configuration: ``max_concurrent_downloads``, ``request_timeout``,
  ``download_chunk_size``, ``verify_ssl``, ``proxies``,
  ``download_parts``, ``download_retries``;
* EDL token: config ``edl_token`` or the ``EDL_TOKEN`` environment
  variable - never a file path in code (validation scripts also read
  ``EDL_TOKEN``).
"""
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    requests = None
    REQUESTS_AVAILABLE = False

logger = logging.getLogger("nisar.access.download")


class DownloadError(RuntimeError):
    """The download could not be completed (auth, server, config...)."""


class DownloadCancelled(RuntimeError):
    """The download was cancelled; part files are kept for a resume."""


def plugin_user_agent() -> str:
    """User-Agent carrying the plugin version (single version source)."""
    try:
        from nisar_qgis import __version__ as version
        return "NISAR-loader/%s" % version
    except Exception:
        return "NISAR-loader"


def edl_headers(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Auth headers for Earthdata Cloud URLs.

    The token comes from the config (QgsAuthManager wiring in the GUI)
    or the ``EDL_TOKEN`` environment variable - never a file path.
    """
    cfg = dict(config or {})
    token = cfg.get("edl_token") or os.environ.get("EDL_TOKEN") or ""
    if token:
        return {"Authorization": "Bearer " + str(token).strip()}
    return {}


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


class _Counter:
    """Thread-safe byte counter for the parallel part downloads."""

    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def add(self, n: int):
        with self._lock:
            self._value += n

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


class DownloadManager:
    """Parallel Range downloader with resume, cancellation and checks."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(config or {})
        self.max_concurrent = max(
            1, _int_or_none(cfg.get("max_concurrent_downloads")) or 2)
        read_timeout = float(cfg.get("request_timeout") or 90)
        self.request_timeout = (10, read_timeout)
        self.chunk_size = max(
            4096, _int_or_none(cfg.get("download_chunk_size"))
            or 1024 * 1024)
        self.verify_ssl = bool(cfg.get("verify_ssl", True))
        self.proxies = cfg.get("proxies") or None
        self.n_parts = max(
            1, _int_or_none(cfg.get("download_parts")) or 4)
        self.retries = max(1, _int_or_none(cfg.get("download_retries")) or 3)
        self.headers = {"User-Agent": plugin_user_agent()}
        self.headers.update(edl_headers(cfg))

    # ----------------------------------------------------------------- http
    def _request(self, method: str, url: str, stream: bool = False,
                 allow_redirects: bool = False,
                 headers: Optional[Dict[str, str]] = None):
        if not REQUESTS_AVAILABLE:
            raise DownloadError(
                "requests is not available (pip install requests)")
        all_headers = dict(self.headers)
        if headers:
            all_headers.update(headers)
        return requests.request(
            method, url, timeout=self.request_timeout,
            verify=self.verify_ssl, proxies=self.proxies,
            headers=all_headers, stream=stream,
            allow_redirects=allow_redirects)

    @staticmethod
    def _content_length(value) -> Optional[int]:
        try:
            n = int(value)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None

    def head_size(self, url: str) -> Optional[int]:
        """Content-Length of the target (HEAD with a Range probe fallback)."""
        try:
            with self._request("HEAD", url, allow_redirects=True) as r:
                if 200 <= r.status_code < 400:
                    n = self._content_length(r.headers.get("Content-Length"))
                    if n:
                        return n
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("HEAD failed for %s: %s", url, exc)
        try:
            with self._request("GET", url, stream=True,
                               allow_redirects=True,
                               headers={"Range": "bytes=0-0"}) as r:
                if r.status_code == 206:
                    content_range = r.headers.get("Content-Range") or ""
                    if "/" in content_range:
                        return self._content_length(
                            content_range.rsplit("/", 1)[-1])
                if 200 <= r.status_code < 400:
                    return self._content_length(
                        r.headers.get("Content-Length"))
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("Range probe failed for %s: %s", url, exc)
        return None

    def estimate_total_size(self, urls) -> Optional[int]:
        """Sum of sizes over the URLs; None when any size is unknown."""
        total = 0
        for url in urls:
            n = self.head_size(url)
            if n is None:
                return None
            total += n
        return total

    @staticmethod
    def check_free_space(output_dir, needed_bytes: int) -> Tuple[bool, int]:
        """(enough_free_space, free_bytes) on the output filesystem."""
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(str(target)).free
        return free >= int(needed_bytes), free

    # ------------------------------------------------------------ downloads
    def download_scene(self, url: str, output_dir, filename: str = None,
                       expected_size: int = 0, cancel_event=None,
                       progress_cb: Optional[Callable] = None,
                       scene_id: str = "") -> Path:
        """Resume-capable download of one granule to the final path.

        The final file appears atomically only after the assembled size
        check. Raises :class:`DownloadCancelled` when cancelled (the
        part files stay for a resume), :class:`DownloadError` on
        irrecoverable failures.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = filename or url.rstrip("/").split("/")[-1]
        final = output_dir / filename
        cancel = cancel_event or threading.Event()
        report = progress_cb or (lambda done, total, status, path: None)

        size = _int_or_none(expected_size) or self.head_size(url) or 0

        # A file under the FINAL name counts as ready only with a
        # matching size (unknown size: accept the existence).
        if final.exists():
            have_size = final.stat().st_size
            if not size or have_size == size:
                report(size, size, "completed", str(final))
                return final
            logger.warning("%s: size %d != expected %d - re-downloading",
                           final, have_size, size)
            try:
                final.unlink()
            except OSError as exc:
                raise DownloadError(
                    "cannot replace the truncated file %s: %s"
                    % (final, exc))

        if not REQUESTS_AVAILABLE:
            raise DownloadError(
                "requests is not available (pip install requests)")

        if size:
            enough, free = self.check_free_space(output_dir, size)
            if not enough:
                raise DownloadError(
                    "not enough disk space for %s: need %d bytes, "
                    "%d free" % (filename, size, free))

        done = _Counter()

        def report_done(status: str = "downloading", path: str = ""):
            report(done.value, size, status, path or str(final))

        report_done("starting")
        if size and self.n_parts > 1 and size > 4 * self.chunk_size:
            bounds = self._split_bounds(size, self.n_parts)
        else:
            # unknown Size or a small file: a single stream to EOF
            bounds = [(0, size - 1 if size else None)]

        futures = []
        with ThreadPoolExecutor(max_workers=len(bounds)) as pool:
            for idx, (start, end) in enumerate(bounds):
                futures.append(pool.submit(
                    self._fetch_part, url, final, idx, start, end,
                    cancel, done, report_done))
            errors: List[BaseException] = []
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    errors.append(exc)
        if cancel.is_set():
            raise DownloadCancelled("download cancelled by user")
        if errors:
            first = errors[0]
            if isinstance(first, (DownloadError, DownloadCancelled)):
                raise first
            raise DownloadError(str(first))

        parts = [Path(str(final) + ".part%d" % i)
                 for i in range(len(bounds))]
        self._assemble_parts(final, size, parts, cancel)
        report(done.value or size, size, "completed", str(final))
        return final

    @staticmethod
    def _split_bounds(size: int, n_parts: int) -> List[Tuple[int, int]]:
        """[start, end] bounds of N parts covering [0, size-1]."""
        bounds: List[Tuple[int, int]] = []
        start = 0
        part_len = size // n_parts
        for i in range(n_parts):
            end = size - 1 if i == n_parts - 1 else start + part_len - 1
            bounds.append((start, end))
            start = end + 1
        return bounds

    def _fetch_part(self, url: str, final: Path, idx: int, start: int,
                    end: Optional[int], cancel: threading.Event,
                    counter: _Counter, report_done: Callable):
        """One Range part, resumed from its existing part file."""
        part_path = Path(str(final) + ".part%d" % idx)
        want = None if end is None else end - start + 1
        have = part_path.stat().st_size if part_path.exists() else 0
        if want is not None and have > want:
            part_path.unlink()
            have = 0

        last_error = None
        attempt = 0
        while want is None or have < want:
            if cancel.is_set():
                raise DownloadCancelled("download cancelled by user")
            attempt += 1
            if attempt > self.retries:
                raise DownloadError(
                    "part %d failed after %d attempts: %s"
                    % (idx, self.retries, last_error))
            if last_error is not None:
                time.sleep(min(2.0, 0.5 * attempt))
            range_end = "" if want is None else str(start + want - 1)
            headers = {"Range": "bytes=%d-%s" % (start + have, range_end)}
            try:
                with self._request("GET", url, stream=True,
                                   allow_redirects=True,
                                   headers=headers) as r:
                    if r.status_code == 200:
                        # the server ignored the Range request: only
                        # acceptable when starting from byte 0
                        if have:
                            raise DownloadError(
                                "server ignored the Range header "
                                "(HTTP 200) - cannot resume part %d" % idx)
                    elif r.status_code != 206:
                        raise DownloadError(
                            "HTTP %s for %s (part %d)"
                            % (r.status_code, url, idx))
                    with open(part_path, "wb" if have == 0 else "ab") as fh:
                        for chunk in r.iter_content(
                                chunk_size=self.chunk_size):
                            if cancel.is_set():
                                raise DownloadCancelled(
                                    "download cancelled by user")
                            if not chunk:
                                continue
                            fh.write(chunk)
                            have += len(chunk)
                            counter.add(len(chunk))
                            report_done()
            except (DownloadCancelled, DownloadError):
                raise
            except Exception as exc:  # network-level: retry with resume
                last_error = "%s: %s" % (type(exc).__name__, exc)
                logger.warning("part %d attempt %d failed: %s",
                               idx, attempt, last_error)
            # the loop resumes from the (larger) part file

    def _assemble_parts(self, final: Path, size: int, parts: List[Path],
                        cancel: threading.Event):
        """Stitch the parts into ``<final>.partial``, verify, rename."""
        partial = Path(str(final) + ".partial")
        with open(partial, "wb") as out:
            for part in parts:
                if cancel.is_set():
                    raise DownloadCancelled("download cancelled by user")
                with open(part, "rb") as fh:
                    shutil.copyfileobj(fh, out, 16 * 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        stitched = partial.stat().st_size
        if size and stitched != size:
            raise DownloadError(
                "assembled size %d does not match the expected %d for %s"
                % (stitched, size, final.name))
        os.replace(str(partial), str(final))
        for part in parts:
            try:
                part.unlink()
            except OSError:  # pragma: no cover - best effort
                pass

    def download_many(self, jobs: List[Dict[str, Any]],
                      progress_cb: Optional[Callable] = None,
                      cancel_event=None):
        """Run granule downloads limited by ``max_concurrent_downloads``.

        ``jobs``: dicts with keys ``url``, ``output_dir``, ``filename``,
        ``expected_size``, ``scene_id``. Returns ``(results, errors)``
        where ``results`` maps scene_id -> final path and ``errors`` is
        a list of ``(scene_id, exception)`` pairs - the caller decides
        how to report them (one consolidated report, never per-scene
        modals).
        """
        results: Dict[str, Path] = {}
        errors: List[Tuple[str, BaseException]] = []
        lock = threading.Lock()

        def _one(job: Dict[str, Any]):
            scene_id = str(job.get("scene_id") or "?")
            try:
                path = self.download_scene(
                    job["url"], job.get("output_dir", "."),
                    filename=job.get("filename"),
                    expected_size=job.get("expected_size") or 0,
                    cancel_event=cancel_event,
                    progress_cb=progress_cb,
                    scene_id=scene_id)
                with lock:
                    results[scene_id] = path
            except Exception as exc:
                with lock:
                    errors.append((scene_id, exc))

        with ThreadPoolExecutor(
                max_workers=self.max_concurrent) as pool:
            list(pool.map(_one, list(jobs)))
        return results, errors
