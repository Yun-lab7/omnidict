"""Cloze cards: the sentence with the word hidden, a hint on the front, and the
dictionary's definition and sound on the back.

Nothing here touches Qt or the collection, so it can be tested on its own.
"""

import html
import re
from dataclasses import dataclass

from .bbc import Episode, Line, find_in_lines, find_sentence, term_pattern

CLOZE_NOTETYPE_NAME = "OmniDict 克漏字"
# The cloze sentence must come first: Anki shows a note by its first field.
CLOZE_FIELDS = ["Text", "Word", "Hint", "Definition", "Source"]
CLOZE_FRONT = (
    '<div class="sentence">{{cloze:Text}}</div>\n'
    '{{#Hint}}<div class="hint">{{Hint}}</div>{{/Hint}}'
)
CLOZE_BACK = (
    CLOZE_FRONT + '\n<hr id="answer">\n<div class="word">{{Word}}</div>\n'
    "{{Definition}}\n"
    '{{#Source}}<div class="source">{{Source}}</div>{{/Source}}'
)
CLOZE_CSS = """.card {
  font-family: arial, sans-serif;
  font-size: 20px;
  text-align: left;
  color: black;
  background-color: white;
}
.sentence {
  padding: 0.5em 0.8em;
  border-left: 4px solid #8ab4f8;
  font-style: italic;
}
.cloze { font-style: normal; font-weight: bold; color: #1a73e8; }
.od-speaker { font-style: normal; font-size: 0.8em; color: #777; white-space: nowrap; }
.hint { margin-top: 0.8em; color: #555; }
.hint::before { content: "💡 "; }
.word { font-size: 28px; font-weight: bold; margin-bottom: 0.3em; }
.source { margin-top: 0.8em; font-size: 0.75em; color: #777; }
.source a { color: inherit; }
.nightMode .card { color: #ddd; background-color: #2f2f31; }
.nightMode .cloze { color: #8ab4f8; }
.nightMode .hint { color: #aaa; }
"""

_HAS_CLOZE = re.compile(r"\{\{c\d+::")


def has_cloze(text: str) -> bool:
    return bool(_HAS_CLOZE.search(text or ""))


@dataclass
class Sentence:
    html: str
    origin: str  # "episode", "dictionary" or "word" (only the word itself)


def build_sentence(
    word: str,
    looked_up: str,
    episode: Episode | None,
    examples: list[str],
    dictionary_name: str,
    *,
    cloze: bool,
) -> Sentence | None:
    """The sentence for a card: the episode's own sentence, else a dictionary example.

    For a cloze note the word is hidden; when no sentence has the word, the card is
    just the hidden word (the hint on the front still says what to recall). For other
    notes the word is bold, and None means no sentence was found.
    """
    alternatives = (looked_up,) if looked_up and looked_up != word else ()
    match = find_sentence(episode, word, alternatives) if episode else None
    origin = "episode"
    if match is None:
        lines = [Line(dictionary_name, s) for s in examples]
        match = find_in_lines(lines, word, alternatives)
        origin = "dictionary"
    if match is not None:
        return Sentence(match.cloze_html() if cloze else match.html(), origin)
    if cloze:
        return Sentence("{{c1::" + html.escape(word) + "}}", "word")
    return None


def mask_word(text: str, *terms: str) -> str:
    """Hide the word in a hint, so the hint doesn't give the answer away."""
    text = text.replace("’", "'")
    for term in terms:
        pattern = term_pattern(term) if term else None
        if pattern is not None:
            text = pattern.sub("___", text)
    return text


def episode_definition(episode: Episode | None, word: str) -> str:
    """The definition from the episode's own word list ("get (something) ready")."""
    if episode is None:
        return ""
    for listed, definition in episode.vocabulary:
        if listed.casefold() == word.casefold():
            return definition
    return ""


def fill_cloze_note(
    fields: list[str],
    names: list[str],
    word: str,
    looked_up: str,
    hint: str,
    examples: list[str],
    dictionary_name: str,
) -> str | None:
    """For the one-key "fetch & add" on a Cloze note: hide the word in the sentence
    field (a dictionary example when it is empty) and fill an empty hint field.

    Changes `fields` in place. Returns a message when the note can't be added as it
    is (the sentence the user typed doesn't contain the word).
    """
    # Imported here: quickadd needs Anki's collection module, this module doesn't.
    from .quickadd import HINT_FIELD_NAMES, SENTENCE_FIELD_NAMES, guess_field

    text_index = guess_field(names, SENTENCE_FIELD_NAMES)
    if text_index is None:
        text_index = 0
    terms = (word, looked_up)
    text = fields[text_index]
    if not re.sub(r"<[^>]*>|&nbsp;|\s", "", text):
        sentence = build_sentence(
            word, looked_up, None, examples, dictionary_name, cloze=True
        )
        fields[text_index] = sentence.html if sentence else ""
    elif not has_cloze(text):
        hidden = cloze_existing(text, *terms)
        if hidden is None:
            return (
                f"「{names[text_index]}」的句子裡找不到「{word}」，"
                "請自己選取要挖空的字按 Ctrl+Shift+C，或清空句子讓外掛放字典例句。"
            )
        fields[text_index] = hidden

    hint_index = guess_field(names, HINT_FIELD_NAMES)
    if hint_index is not None and not fields[hint_index].strip() and hint:
        fields[hint_index] = html.escape(mask_word(hint, *terms))
    return None


def cloze_existing(text: str, *terms: str) -> str | None:
    """Hide the word in a sentence the user typed; None if the word isn't in it.

    Only text outside HTML tags is searched, so attributes are never changed.
    """
    parts = re.split(r"(<[^>]*>)", text)
    for term in terms:
        pattern = term_pattern(term) if term else None
        if pattern is None:
            continue
        for i, part in enumerate(parts):
            if part.startswith("<"):
                continue
            # Search a copy where entities are as long as before but read as the
            # character they stand for ("break&nbsp;the ice"), so offsets still fit.
            searchable = re.sub(
                r"&(?:nbsp|#160);",
                lambda m: " " * len(m.group()),
                part.replace("’", "'"),
            )
            searchable = re.sub(
                r"&amp;", lambda m: "&" + " " * (len(m.group()) - 1), searchable
            )
            found = pattern.search(searchable)
            if found:
                parts[i] = (
                    part[: found.start()]
                    + "{{c1::"
                    + part[found.start() : found.end()]
                    + "}}"
                    + part[found.end() :]
                )
                return "".join(parts)
    return None
