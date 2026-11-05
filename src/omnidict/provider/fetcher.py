"""How a provider gets pages and files from the web.

Inside Anki, pages are loaded in a real browser (Qt WebEngine, see `browser.py`):
on many networks Cloudflare answers plain `requests` with 403, while a browser passes
its check normally, and the user is shown the check when it asks for a person.
Outside Anki (tests, scripts) the original `requests` session is kept.
"""

from dataclasses import dataclass
from typing import Protocol

from requests import Session


@dataclass
class PageResponse:
    """A loaded page.

    Attributes:
        url: The final URL, after any redirects.
        text: The page's HTML.
    """

    url: str
    text: str


class Fetcher(Protocol):
    def get_page(self, url: str) -> PageResponse: ...

    def get_bytes(self, url: str) -> bytes: ...

    def close(self) -> None: ...


class RequestsFetcher:
    """Plain HTTP requests, for use outside Anki."""

    def __init__(self, headers: dict[str, str]):
        self.session = Session()
        self.session.headers.update(headers)

    def get_page(self, url: str) -> PageResponse:
        response = self.session.get(url)
        response.raise_for_status()
        return PageResponse(url=response.url, text=response.text)

    def get_bytes(self, url: str) -> bytes:
        response = self.session.get(url)
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        self.session.close()


class BrowserFetcher:
    """A real browser inside Anki. Must be called from a background thread."""

    def get_page(self, url: str) -> PageResponse:
        from .browser import fetch_page

        return fetch_page(url)

    def get_bytes(self, url: str) -> bytes:
        from .browser import fetch_bytes

        return fetch_bytes(url)

    def close(self) -> None:
        pass


def running_in_anki() -> bool:
    try:
        from aqt import mw
    except ImportError:
        return False
    return mw is not None
