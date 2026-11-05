import pytest

from omnidict.provider.cambridge import CambridgeDictionaryProvider
from omnidict.provider.common import DefinitionNotFoundError, DefinitionParseError
from omnidict.provider.fetcher import PageResponse, RequestsFetcher, running_in_anki


class FakeFetcher:
    def __init__(self, page: PageResponse):
        self.page = page
        self.requested: list[str] = []
        self.closed = False

    def get_page(self, url: str) -> PageResponse:
        self.requested.append(url)
        return self.page

    def get_bytes(self, url: str) -> bytes:
        raise AssertionError("no download expected")

    def close(self) -> None:
        self.closed = True


def test_outside_anki_uses_requests():
    assert not running_in_anki()
    provider = CambridgeDictionaryProvider()
    assert isinstance(provider.fetcher, RequestsFetcher)


def test_searches_through_the_fetcher():
    fetcher = FakeFetcher(
        PageResponse(
            url="https://dictionary.cambridge.org/spellcheck/english/?q=dgo", text=""
        )
    )
    provider = CambridgeDictionaryProvider(fetcher)

    with pytest.raises(DefinitionNotFoundError):
        provider.fetch_definition(
            "english-advanced-learner", "dgo", download_audio=False
        )

    assert fetcher.requested == [
        "https://dictionary.cambridge.org/search/direct/?datasetsearch=english&q=dgo"
    ]


def test_reads_the_final_url_of_the_page():
    fetcher = FakeFetcher(
        PageResponse(url="https://dictionary.cambridge.org/unexpected/", text="")
    )
    provider = CambridgeDictionaryProvider(fetcher)

    with pytest.raises(DefinitionParseError, match="unexpected response URL"):
        provider.fetch_definition(
            "english-advanced-learner", "dog", download_audio=False
        )


def test_closes_the_fetcher():
    fetcher = FakeFetcher(PageResponse(url="", text=""))
    provider = CambridgeDictionaryProvider(fetcher)

    provider.__del__()

    assert fetcher.closed
