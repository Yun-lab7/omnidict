import pytest

from omnidict.provider import (
    DefinitionNotFoundError,
    DefinitionRedirectedError,
    ProviderManager,
)
from omnidict.quickadd import (
    batch_config,
    clean_word,
    default_dictionary,
    definition_config,
    describe_error,
    fetch_definition_html,
    find_field_indices,
    lookup_term,
    parse_word_list,
    quick_add_config,
    resolve_dictionary,
)


class FakeDefinition:
    def __init__(self, word, dictionary_id):
        self.word, self.dictionary_id = word, dictionary_id
        self.saved = False
        self.entries = []

    def save_audio_files(self, col):
        self.saved = True

    def render_html(self, **options):
        assert set(options) == {
            "include_audio",
            "include_phonemic_transcriptions",
            "include_translations",
            "include_examples",
        }
        return f"<b>{self.word}</b>@{self.dictionary_id}"


class FakeProvider:
    def __init__(self, redirects=None, missing=()):
        self.redirects = redirects or {}
        self.missing = set(missing)
        self.calls = []
        self.last = None

    def fetch_definition(self, dictionary_id, term, *, download_audio):
        self.calls.append((dictionary_id, term, download_audio))
        if (dictionary_id, term) in self.redirects:
            raise DefinitionRedirectedError(*self.redirects[(dictionary_id, term)])
        if term in self.missing:
            raise DefinitionNotFoundError(term)
        self.last = FakeDefinition(term, dictionary_id)
        return self.last


OPTIONS = definition_config(None)


def test_parse_word_list():
    text = "apple\n\n  break   the ice \n# comment\nApple\nrecord\xa0\n"
    assert parse_word_list(text) == ["apple", "break the ice", "record"]


def test_clean_word():
    assert clean_word("&nbsp;<b>dog</b>&nbsp;<br>") == "dog"
    assert clean_word("break&nbsp;the ice") == "break the ice"
    assert clean_word("") == ""
    assert clean_word("<b>do</b>g") == "dog"
    assert clean_word("rock &amp; roll<div>x</div>") == "rock & roll x"


def test_find_field_indices_defaults_and_names():
    assert find_field_indices(["Front", "Back"], None) == (0, 1)
    config = {"quick_add": {"word_field": "word", "definition_field": "MEANING"}}
    assert find_field_indices(["Meaning", "Word", "x"], config) == (1, 0)
    with pytest.raises(ValueError):
        find_field_indices(["Front", "Back"], {"quick_add": {"word_field": "nope"}})
    with pytest.raises(ValueError):
        find_field_indices(["Text"], None)
    with pytest.raises(ValueError):
        find_field_indices(
            ["A", "B"], {"quick_add": {"word_field": "A", "definition_field": "a"}}
        )


def test_config_defaults_and_old_user_config():
    # A user config written before this feature has no quick_add / batch sections.
    old = {"editor": {"buttons": ["cambridge-dictionary.english-advanced-learner"]}}
    assert default_dictionary(old) == "cambridge-dictionary.english-advanced-learner"
    assert quick_add_config(old)["shortcut"] == "Ctrl+Shift+Return"
    assert quick_add_config(old)["follow_redirects"] is True
    assert batch_config(old)["delay_seconds"] == 1.5
    assert batch_config({"batch": {"delay_seconds": "x"}})["delay_seconds"] == 1.5
    assert batch_config({"batch": {"delay_seconds": -3}})["delay_seconds"] == 0
    assert (
        default_dictionary(None) == "cambridge-dictionary.english-chinese-traditional"
    )
    assert default_dictionary({"quick_add": {"dictionary": "a.b"}, **old}) == "a.b"
    assert definition_config({"definition": {"include_audio": True, "junk": 1}}) == {
        **OPTIONS,
        "include_audio": True,
    }


def test_resolve_dictionary(monkeypatch):
    # The real one reads the add-on config, which needs a running Anki.
    monkeypatch.setattr(
        ProviderManager, "_instantiate_provider", staticmethod(lambda klass: klass())
    )
    manager = ProviderManager()
    ids = [full_id for full_id, _ in manager.list_dictionaries()]
    assert "cambridge-dictionary.english-chinese-traditional" in ids
    _provider, dictionary_id = resolve_dictionary(
        manager, "cambridge-dictionary.english-advanced-learner"
    )
    assert dictionary_id == "english-advanced-learner"
    for bad in ("nodot", "nope.english", "cambridge-dictionary.nope"):
        with pytest.raises(ValueError):
            resolve_dictionary(manager, bad)


def test_fetch_plain():
    provider = FakeProvider()
    result = fetch_definition_html(None, provider, "d1", "dog", OPTIONS)
    assert result.html == "<b>dog</b>@d1"
    assert not result.redirected
    assert provider.calls == [("d1", "dog", False)]


def test_fetch_follows_word_and_dictionary_redirects():
    provider = FakeProvider(
        redirects={("d1", "clicked"): ("click", None), ("d1", "click"): ("click", "d2")}
    )
    result = fetch_definition_html(None, provider, "d1", "clicked", OPTIONS)
    assert (result.word, result.dictionary_id, result.redirected) == (
        "click",
        "d2",
        True,
    )
    assert result.html == "<b>click</b>@d2"


def test_fetch_redirect_not_followed_when_disabled():
    provider = FakeProvider(redirects={("d1", "clicked"): ("click", None)})
    with pytest.raises(DefinitionRedirectedError):
        fetch_definition_html(
            None, provider, "d1", "clicked", OPTIONS, follow_redirects=False
        )


def test_fetch_redirect_loop_stops():
    provider = FakeProvider(
        redirects={("d1", "a"): ("b", None), ("d1", "b"): ("a", None)}
    )
    with pytest.raises(DefinitionNotFoundError):
        fetch_definition_html(None, provider, "d1", "a", OPTIONS)
    assert len(provider.calls) == 4
    # Redirect to itself is reported instead of retried.
    provider = FakeProvider(redirects={("d1", "x"): ("x", "d1")})
    with pytest.raises(DefinitionRedirectedError):
        fetch_definition_html(None, provider, "d1", "x", OPTIONS)


def test_fetch_saves_audio_only_when_asked():
    provider = FakeProvider()
    fetch_definition_html(object(), provider, "d1", "dog", OPTIONS)
    assert provider.last.saved is False
    fetch_definition_html(
        object(), provider, "d1", "dog", {**OPTIONS, "include_audio": True}
    )
    assert provider.last.saved is True
    assert provider.calls[-1] == ("d1", "dog", True)


def test_describe_error():
    assert "找不到" in describe_error(DefinitionNotFoundError("x"), "dog")
    assert "click" in describe_error(
        DefinitionRedirectedError("click", "d2"), "clicked"
    )
    assert "boom" in describe_error(RuntimeError("boom"), "dog")


def test_lookup_term():
    assert lookup_term("prime (something)") == "prime"
    assert lookup_term("get [sth] ready") == "get ready"
    assert lookup_term("break the ice") == "break the ice"
    assert lookup_term("(x)") == "(x)"
