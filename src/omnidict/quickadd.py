"""Shared pieces for the one-key "fetch & add" button and the batch-add dialog.

Nothing in this module touches Qt, so it can be tested without a running Anki window.
"""

import html
import re
from dataclasses import dataclass
from typing import Any

from anki.collection import Collection

from .provider import (
    DefinitionNotFoundError,
    DefinitionParseError,
    DefinitionRedirectedError,
    Provider,
)

DEFAULT_DICTIONARY = "cambridge-dictionary.english-chinese-traditional"
DEFAULT_QUICK_ADD_SHORTCUT = "Ctrl+Shift+Return"
DEFAULT_BATCH_SHORTCUT = "Ctrl+Shift+B"
DEFAULT_BATCH_DELAY_SECONDS = 1.5
# A redirect can point to another word and then to another dictionary; never loop forever.
MAX_REDIRECTS = 3


def _section(config: dict | None, name: str) -> dict:
    value = (config or {}).get(name)
    return value if isinstance(value, dict) else {}


def definition_config(config: dict | None) -> dict[str, bool]:
    """What to put in the definition. A copy, so the add-on config is never changed."""
    result = {
        "include_audio": False,
        "include_phonemic_transcriptions": True,
        "include_translations": True,
        "include_examples": False,
    }
    for key, value in _section(config, "definition").items():
        if key in result:
            result[key] = bool(value)
    return result


def quick_add_config(config: dict | None) -> dict[str, Any]:
    section = _section(config, "quick_add")
    return {
        "shortcut": section.get("shortcut") or DEFAULT_QUICK_ADD_SHORTCUT,
        "word_field": section.get("word_field") or "",
        "definition_field": section.get("definition_field") or "",
        "dictionary": section.get("dictionary") or "",
        "follow_redirects": bool(section.get("follow_redirects", True)),
    }


def batch_config(config: dict | None) -> dict[str, Any]:
    section = _section(config, "batch")
    try:
        delay = float(section.get("delay_seconds", DEFAULT_BATCH_DELAY_SECONDS))
    except (TypeError, ValueError):
        delay = DEFAULT_BATCH_DELAY_SECONDS
    return {
        "delay_seconds": max(0.0, delay),
        "menu_shortcut": section.get("menu_shortcut", DEFAULT_BATCH_SHORTCUT) or "",
    }


def default_dictionary(config: dict | None) -> str:
    """`quick_add.dictionary`, else the first editor button, else Cambridge 英漢（繁體）."""
    chosen = quick_add_config(config)["dictionary"]
    if chosen:
        return chosen
    buttons = _section(config, "editor").get("buttons")
    if isinstance(buttons, list) and buttons and isinstance(buttons[0], str):
        return buttons[0]
    return DEFAULT_DICTIONARY


def resolve_dictionary(provider_manager, full_id: str) -> tuple[Provider, str]:
    """Turn "provider.dictionary" into the provider object and the dictionary id."""
    parts = full_id.split(".")
    if len(parts) != 2:
        raise ValueError(f"字典設定格式不對：{full_id}（應該是 provider.dictionary）")
    provider_id, dictionary_id = parts
    provider = provider_manager.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"找不到字典來源：{provider_id}")
    if provider.get_dictionary_info(dictionary_id) is None:
        raise ValueError(f"{provider.name()} 沒有這本字典：{dictionary_id}")
    return provider, dictionary_id


def clean_word(field_html: str) -> str:
    """The word as typed in the field, without HTML, &nbsp; or extra spaces."""
    # Not anki.utils.strip_html: that needs an open collection's backend.
    text = re.sub(
        r"</?(?:br|div|p|li)\b[^>]*>", " ", field_html or "", flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]*>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return " ".join(text.split())


def parse_word_list(text: str) -> list[str]:
    """One word or phrase per line. Blank lines and lines starting with # are skipped;
    repeats (ignoring case) are kept only once, in their first position."""
    words: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        word = " ".join(line.replace("\xa0", " ").split())
        if not word or word.startswith("#"):
            continue
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            words.append(word)
    return words


def find_field_indices(field_names: list[str], config: dict | None) -> tuple[int, int]:
    """Index of the word field and of the definition field.

    Uses `quick_add.word_field` / `quick_add.definition_field` when set; otherwise the
    first field is the word and the second field is the definition.
    """
    section = quick_add_config(config)
    lowered = [name.casefold() for name in field_names]

    def index_of(name: str, fallback: int, label: str) -> int:
        if name:
            try:
                return lowered.index(name.casefold())
            except ValueError:
                raise ValueError(
                    f"這個筆記類型沒有叫「{name}」的欄位（設定裡的 {label}）。"
                ) from None
        if fallback >= len(field_names):
            raise ValueError("這個筆記類型只有一個欄位，至少要兩個欄位（單字、釋義）。")
        return fallback

    word_index = index_of(section["word_field"], 0, "quick_add.word_field")
    definition_index = index_of(
        section["definition_field"], 1, "quick_add.definition_field"
    )
    if word_index == definition_index:
        raise ValueError("單字欄位和釋義欄位不能是同一個。")
    return word_index, definition_index


@dataclass
class FetchResult:
    html: str
    word: str  # what was actually looked up (may differ after a redirect)
    dictionary_id: str
    redirected: bool


def fetch_definition_html(
    col: Collection | None,
    provider: Provider,
    dictionary_id: str,
    word: str,
    definition_options: dict[str, bool],
    *,
    follow_redirects: bool = True,
) -> FetchResult:
    """Look the word up and return ready-to-store HTML. Runs in a background thread.

    Raises the provider's errors (`DefinitionNotFoundError`, ...). A redirect is followed
    automatically when `follow_redirects` is true, otherwise `DefinitionRedirectedError`
    is raised as before.
    """
    term, current_dictionary, redirected = word, dictionary_id, False
    for _ in range(MAX_REDIRECTS + 1):
        try:
            definition = provider.fetch_definition(
                current_dictionary,
                term,
                download_audio=definition_options["include_audio"],
            )
        except DefinitionRedirectedError as e:
            if not follow_redirects:
                raise
            next_dictionary = e.redirected_dictionary_id or current_dictionary
            if (e.redirected_word, next_dictionary) == (term, current_dictionary):
                raise
            term, current_dictionary, redirected = (
                e.redirected_word,
                next_dictionary,
                True,
            )
            continue

        if definition_options["include_audio"] and col is not None:
            definition.save_audio_files(col)
        return FetchResult(
            html=definition.render_html(**definition_options),
            word=term,
            dictionary_id=current_dictionary,
            redirected=redirected,
        )
    raise DefinitionNotFoundError(f"太多次轉址，放棄查詢 {word}")


def describe_error(error: Exception, word: str) -> str:
    """A short message for the user, in the language of this fork."""
    if isinstance(error, DefinitionNotFoundError):
        return f"字典裡找不到「{word}」"
    if isinstance(error, DefinitionRedirectedError):
        target = error.redirected_word
        if error.redirected_dictionary_id:
            target += f"（{error.redirected_dictionary_id}）"
        return f"「{word}」被轉到「{target}」"
    if isinstance(error, DefinitionParseError):
        return f"解析「{word}」的頁面失敗：{error}"
    return f"查詢「{word}」時出錯：{error}"
