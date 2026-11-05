"""Fetch Cambridge pages through a real browser (Qt WebEngine) instead of `requests`.

Cloudflare answers plain Python requests with 403. A real browser engine passes its
check the normal way; when Cloudflare asks a person to confirm, the window is shown and
the user answers it themselves. Nothing here fakes a browser or solves the check.

The provider runs in a background thread (QueryOp). Qt objects live on the main
thread, so each request is handed to the main thread and the caller waits for it.
"""

import json
import threading
import time
from base64 import b64decode
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from aqt import gui_hooks, mw
from PyQt6.QtCore import QObject, Qt, QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from requests.exceptions import RequestException

from .fetcher import PageResponse

ORIGIN = "https://dictionary.cambridge.org"
_ALLOWED_HOSTS = ("dictionary.cambridge.org", "challenges.cloudflare.com")

POLL_MILLIS = 500
# Cloudflare's check often clears by itself; show the window only after this long.
PERSON_DELAY_SECONDS = 8
# Without any check, a page that takes longer than this is shown to the user too.
QUIET_TIMEOUT_SECONDS = 30
# Once the window is shown, the user has this long to finish.
PERSON_TIMEOUT_SECONDS = 300
WAIT_LIMIT_SECONDS = PERSON_TIMEOUT_SECONDS + 60

_PROBE = """
JSON.stringify({
  href: location.href,
  ready: document.readyState,
  challenge: !document.querySelector('.pr.dictionary')
    && location.pathname.indexOf('/spellcheck/') < 0
    && !!(window._cf_chl_opt || document.querySelector(
      '#challenge-error-text, #challenge-form, script[src*="/cdn-cgi/challenge-platform/"]'))
})
"""

_START_DOWNLOAD = """
(function (url, key) {
  window.__omnidict = window.__omnidict || {};
  window.__omnidict[key] = { state: 'pending' };
  fetch(url, { credentials: 'include' })
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.arrayBuffer();
    })
    .then(function (buffer) {
      var bytes = new Uint8Array(buffer), s = '';
      for (var i = 0; i < bytes.length; i += 0x8000)
        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      window.__omnidict[key] = { state: 'done', data: btoa(s) };
    })
    .catch(function (e) {
      window.__omnidict[key] = { state: 'error', error: String(e) };
    });
})(%s, %s);
"""

_READ_DOWNLOAD = """
(function (key) {
  var r = (window.__omnidict || {})[key];
  if (r && r.state !== 'pending') delete window.__omnidict[key];
  return JSON.stringify(r || { state: 'missing' });
})(%s);
"""


Done = Callable[[Any, str | None], None]


class BrowserFetchError(RequestException):
    """Raised when the browser could not get a page or file."""


class _Page(QWebEnginePage):
    def acceptNavigationRequest(
        self, url: QUrl, type: QWebEnginePage.NavigationType, isMainFrame: bool
    ) -> bool:
        if isMainFrame and url.host() not in _ALLOWED_HOSTS:
            return False
        return super().acceptNavigationRequest(url, type, isMainFrame)


class _Browser(QObject):
    """One hidden browser window, used on the main thread only."""

    def __init__(self):
        super().__init__(mw)
        # A named profile keeps its cookies on disk, so Cloudflare's pass is remembered.
        self.profile = QWebEngineProfile("omnidict-cambridge", self)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self.dialog = QDialog(mw)
        self.dialog.setWindowTitle("OmniDict - Cambridge")
        self.dialog.resize(900, 700)
        label = QLabel(
            "Cambridge 要確認你是人類。請在下面完成驗證，完成後會自動繼續查字。\n"
            "關掉這個視窗會取消這次查詢。"
        )
        label.setWordWrap(True)
        self.view = QWebEngineView(self.dialog)
        self.page = _Page(self.profile, self.view)
        self.view.setPage(self.page)
        layout = QVBoxLayout(self.dialog)
        layout.addWidget(label)
        layout.addWidget(self.view, 1)
        self.dialog.rejected.connect(self._on_dialog_closed)

        self.loading = False
        self.page.loadStarted.connect(self._on_load_started)
        self.page.loadFinished.connect(self._on_load_finished)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MILLIS)
        self.timer.timeout.connect(self._poll)

        self.job: _Job | None = None
        self.download_counter = 0

    # ---- jobs --------------------------------------------------------------

    def start_page(self, url: str, done) -> None:
        self._begin(_Job(kind="page", url=url, done=done))
        self.loading = True
        self.page.load(QUrl(url))

    def start_download(self, url: str, done) -> None:
        host = urlsplit(self.page.url().toString()).hostname
        if host == "dictionary.cambridge.org" and not self.loading:
            self._begin(_Job(kind="download", url=url, done=done))
            self._start_fetch()
            return

        # The download runs inside a Cambridge page, so open one first.
        def after_home(_result, error):
            if error:
                done(None, error)
            else:
                self.start_download(url, done)

        self.start_page(ORIGIN + "/", after_home)

    def _begin(self, job: "_Job") -> None:
        if self.job is not None:
            self._finish(None, "被新的查詢取代")
        self.job = job
        self.timer.start()

    def _finish(self, result, error) -> None:
        job, self.job = self.job, None
        self.timer.stop()
        if self.dialog.isVisible():
            self.dialog.hide()
        if job is not None:
            job.done(result, error)

    # ---- page loading ------------------------------------------------------

    def _on_load_started(self) -> None:
        self.loading = True

    def _on_load_finished(self, _ok: bool) -> None:
        self.loading = False
        self._poll()

    def _on_dialog_closed(self) -> None:
        if self.job is not None:
            self.page.triggerAction(QWebEnginePage.WebAction.Stop)
            self._finish(None, "已取消：Cambridge 的驗證視窗被關掉了")

    def _poll(self) -> None:
        job = self.job
        if job is None:
            return
        now = time.monotonic()
        if job.shown_at is not None:
            if now - job.shown_at > PERSON_TIMEOUT_SECONDS:
                self._finish(None, "等太久了，Cambridge 的驗證沒有完成")
                return
        elif job.challenge_since is not None:
            if now - job.challenge_since > PERSON_DELAY_SECONDS:
                self._show_dialog(job)
        elif now - job.started_at > QUIET_TIMEOUT_SECONDS:
            # Something is slow or wrong; let the user see the page.
            self._show_dialog(job)

        if job.kind == "page":
            if not self.loading:
                self.page.runJavaScript(_PROBE, lambda raw: self._on_probe(job, raw))
        else:
            script = _READ_DOWNLOAD % json.dumps(job.key)
            self.page.runJavaScript(script, lambda raw: self._on_download(job, raw))

    def _show_dialog(self, job: "_Job") -> None:
        job.shown_at = time.monotonic()
        # Anki's progress window is modal; this one has to be on top of it to take clicks.
        self.dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _on_probe(self, job: "_Job", raw) -> None:
        if job is not self.job or self.loading or not isinstance(raw, str):
            return
        try:
            probe = json.loads(raw)
        except ValueError:
            return
        if probe.get("challenge"):
            if job.challenge_since is None:
                job.challenge_since = time.monotonic()
            return
        href = probe.get("href", "")
        if (
            probe.get("ready") != "complete"
            or urlsplit(href).hostname != "dictionary.cambridge.org"
        ):
            return
        if job.reading:
            return
        job.reading = True
        self.page.toHtml(lambda html: self._on_html(job, href, html))

    def _on_html(self, job: "_Job", href: str, html) -> None:
        if job is not self.job:
            return
        if not html:
            job.reading = False
            return
        self._finish(PageResponse(url=href, text=html), None)

    # ---- downloads ---------------------------------------------------------

    def _start_fetch(self) -> None:
        job = self.job
        assert job is not None
        self.download_counter += 1
        job.key = f"d{self.download_counter}"
        script = _START_DOWNLOAD % (json.dumps(job.url), json.dumps(job.key))
        self.page.runJavaScript(script)

    def _on_download(self, job: "_Job", raw) -> None:
        if job is not self.job or not isinstance(raw, str):
            return
        try:
            result = json.loads(raw)
        except ValueError:
            return
        state = result.get("state")
        if state == "done":
            self._finish(b64decode(result.get("data", "")), None)
        elif state == "error":
            self._finish(None, f"下載失敗：{result.get('error')}")
        elif state == "missing":
            # The page navigated away and lost the download; start it again.
            self._start_fetch()

    def dispose(self) -> None:
        if self.job is not None:
            self._finish(None, "Anki 正在關閉")
        self.timer.stop()
        self.dialog.hide()
        self.view.setPage(None)
        self.page.deleteLater()
        self.dialog.deleteLater()
        self.deleteLater()


@dataclass
class _Job:
    kind: str
    url: str
    done: "Done"
    started_at: float = 0.0
    challenge_since: float | None = None
    shown_at: float | None = None
    reading: bool = False
    key: str = ""

    def __post_init__(self):
        self.started_at = time.monotonic()


_browser: _Browser | None = None
_request_lock = threading.Lock()


def _get_browser() -> _Browser:
    global _browser
    if _browser is None:
        _browser = _Browser()
    return _browser


def _dispose_browser(*_args) -> None:
    global _browser
    if _browser is not None:
        _browser.dispose()
        _browser = None


gui_hooks.profile_will_close.append(_dispose_browser)


def _run_on_main(start):
    if threading.current_thread() is threading.main_thread():
        raise BrowserFetchError("內部錯誤：不能在 Anki 的主執行緒等待瀏覽器")

    with _request_lock:
        finished = threading.Event()
        box: dict = {}

        def done(result, error):
            if not finished.is_set():
                box["result"], box["error"] = result, error
                finished.set()

        def begin():
            try:
                start(_get_browser(), done)
            except Exception as e:  # noqa: BLE001 - report anything to the caller
                done(None, f"瀏覽器啟動失敗：{e}")

        mw.taskman.run_on_main(begin)
        if not finished.wait(WAIT_LIMIT_SECONDS):
            raise BrowserFetchError("等太久了，沒有拿到 Cambridge 的資料")
        if box.get("error"):
            raise BrowserFetchError(box["error"])
        return box["result"]


def fetch_page(url: str) -> PageResponse:
    """Load `url` in the browser and return the final URL and the page's HTML."""
    return _run_on_main(lambda browser, done: browser.start_page(url, done))


def fetch_bytes(url: str) -> bytes:
    """Download `url` from inside a Cambridge page, with the browser's cookies."""
    return _run_on_main(lambda browser, done: browser.start_download(url, done))
