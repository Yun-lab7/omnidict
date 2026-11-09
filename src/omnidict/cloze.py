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
# The whole sentence is read aloud on the back (Anki's text-to-speech, British
# English); the front stays silent so it doesn't give the word away.
TTS_LANG = "en_GB"
CLOZE_BACK = (
    CLOZE_FRONT + '\n<hr id="answer">\n<div class="word">{{Word}}</div>\n'
    "{{Definition}}\n"
    f'<div class="read-aloud">{{{{tts {TTS_LANG}:cloze:Text}}}}</div>\n'
    '{{#Source}}<div class="source">{{Source}}</div>{{/Source}}'
)
# Back templates of earlier versions, upgraded to CLOZE_BACK when found unchanged.
OLD_CLOZE_BACKS = (
    CLOZE_FRONT + '\n<hr id="answer">\n<div class="word">{{Word}}</div>\n'
    "{{Definition}}\n"
    '{{#Source}}<div class="source">{{Source}}</div>{{/Source}}',
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
.read-aloud { margin-top: 0.5em; }
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
    # Who said it ("Becca", "Cambridge Dictionary"). For a cloze note it is kept out
    # of the sentence (which is read aloud) and shown with the source instead.
    speaker: str = ""


def speaker_html(speaker: str) -> str:
    return f'<span class="od-speaker">{html.escape(speaker)}</span>' if speaker else ""


def with_speaker(source_html: str, speaker: str) -> str:
    """ "Becca · <a>Real Easy English · …</a>"."""
    return " · ".join(p for p in (speaker_html(speaker), source_html) if p)


_SPEAKER_IN_TEXT = re.compile(
    r'\s*<span class="od-speaker">—\s*(.*?)</span>\s*$', re.DOTALL
)


def move_speaker_to_source(text: str, source: str) -> tuple[str, str] | None:
    """For notes made before the sentence was read aloud: take "— Becca" out of the
    sentence and put it in front of the source. None if there's nothing to move."""
    found = _SPEAKER_IN_TEXT.search(text)
    if not found:
        return None
    speaker = html.unescape(found.group(1)).strip()
    return text[: found.start()], with_speaker(source, speaker)


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
        if cloze:
            return Sentence(match.cloze_html(), origin, match.speaker)
        return Sentence(match.html(), origin, match.speaker)
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
    from .quickadd import (
        HINT_FIELD_NAMES,
        SENTENCE_FIELD_NAMES,
        SOURCE_FIELD_NAMES,
        guess_field,
    )

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
        source_index = guess_field(names, SOURCE_FIELD_NAMES)
        if (
            sentence is not None
            and sentence.speaker
            and source_index is not None
            and not fields[source_index].strip()
        ):
            fields[source_index] = speaker_html(sentence.speaker)
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
