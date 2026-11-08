"""Read a BBC Learning English episode page (e.g. 6 Minute English).

From the page we take the title, episode number and date (for the "source" of a card),
the episode's vocabulary list, and the transcript split into sentences, so that each
word can be shown with the sentence it was heard in.

Nothing here touches Qt or the collection, so it can be tested on its own.
"""

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

ALLOWED_HOST_SUFFIX = "bbc.co.uk"
# Words in a phrase that stand for "any words here", e.g. "prime (something)".
_PLACEHOLDERS = {
    "something",
    "someone",
    "somebody",
    "sth",
    "sb",
    "one's",
    "someone's",
    "somebody's",
    "your",
}
# Irregular past forms of verbs common in phrasal verbs and idioms.
_IRREGULAR = {
    "be": "am is are was were been being",
    "become": "became",
    "begin": "began begun",
    "break": "broke broken",
    "bring": "brought",
    "buy": "bought",
    "catch": "caught",
    "choose": "chose chosen",
    "come": "came",
    "do": "does did done doing",
    "draw": "drew drawn",
    "drive": "drove driven",
    "eat": "ate eaten",
    "fall": "fell fallen",
    "feel": "felt",
    "fight": "fought",
    "find": "found",
    "fly": "flew flown",
    "forget": "forgot forgotten",
    "get": "got gotten getting",
    "give": "gave given",
    "go": "goes went gone going",
    "grow": "grew grown",
    "have": "has had having",
    "hold": "held",
    "keep": "kept",
    "know": "knew known",
    "lay": "laid",
    "lead": "led",
    "leave": "left",
    "lose": "lost",
    "make": "made",
    "mean": "meant",
    "meet": "met",
    "pay": "paid",
    "ride": "rode ridden",
    "rise": "rose risen",
    "run": "ran running",
    "say": "said",
    "see": "saw seen",
    "sell": "sold",
    "send": "sent",
    "set": "setting",
    "shake": "shook shaken",
    "show": "shown",
    "sit": "sat",
    "speak": "spoke spoken",
    "spend": "spent",
    "stand": "stood",
    "stick": "stuck",
    "take": "took taken",
    "teach": "taught",
    "tear": "tore torn",
    "tell": "told",
    "think": "thought",
    "throw": "threw thrown",
    "wear": "wore worn",
    "win": "won winning",
    "write": "wrote written",
}
_SENTENCE_END = re.compile(r"(?<=[.?!…])[\"'”’)]*\s+(?=[\"'“‘(]?[A-Z0-9])")


@dataclass
class Line:
    speaker: str
    sentence: str


@dataclass
class Episode:
    url: str
    programme: str = ""
    title: str = ""
    number: str = ""
    date: str = ""
    vocabulary: list[tuple[str, str]] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    @property
    def tag(self) -> str:
        """e.g. "6min::261105"; empty when the page has no episode number."""
        if not self.number:
            return ""
        short = {"6 Minute English": "6min"}.get(self.programme)
        prefix = short or re.sub(r"\W+", "-", self.programme.lower()).strip("-")
        return f"{prefix or 'bbc'}::{self.number}"

    def source_html(self) -> str:
        name = " · ".join(p for p in (self.programme, self.title) if p)
        name = html.escape(name or self.url)
        text = f'<a href="{html.escape(self.url)}">{name}</a>' if self.url else name
        if self.date:
            text += f" · {html.escape(self.date)}"
        return text

    def summary(self) -> str:
        return (
            f"{self.title or self.url}（{len(self.vocabulary)} 個單字、"
            f"逐字稿 {len(self.lines)} 句）"
        )


class EpisodeError(RuntimeError):
    pass


def check_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not (
        host == ALLOWED_HOST_SUFFIX or host.endswith("." + ALLOWED_HOST_SUFFIX)
    ):
        raise EpisodeError(
            "請貼 BBC Learning English 的節目網址（bbc.co.uk/learningenglish/…）"
        )
    return url


def load_episode(source: str, fetch_text) -> Episode:
    """`source` is an episode URL or the path of a page saved with Ctrl+S.

    `fetch_text(url) -> str` downloads a page; it is passed in so tests need no network.
    """
    source = source.strip().strip('"')
    path = Path(source)
    if not source.lower().startswith(("http://", "https://")) and path.is_file():
        page = path.read_text(encoding="utf-8", errors="replace")
        saved_from = re.search(r"saved from url=\(\d+\)(\S+)", page[:500])
        return parse_episode(page, saved_from.group(1) if saved_from else "")
    url = check_url(source)
    return parse_episode(fetch_text(url), url)


# --------------------------------------------------------------------------- parsing
def parse_episode(page: str, url: str = "") -> Episode:
    soup = BeautifulSoup(page, "html.parser")
    episode = Episode(url=url)

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # "BBC Learning English - 6 Minute English / Could vaccines cure cancer?"
    match = re.match(r"BBC Learning English\s*-\s*(.+?)\s*/\s*(.+)$", title)
    if match:
        episode.programme, episode.title = match.group(1), match.group(2)
    else:
        episode.title = title

    header = soup.select_one(".widget-bbcle-featuresubheader .details")
    if header is not None:
        text = header.get_text(" ", strip=True)
        number = re.search(r"Episode\s+(\w+)", text)
        date = re.search(r"/\s*(\d{1,2}\s+\w+\s+\d{4})", text)
        episode.number = number.group(1) if number else ""
        episode.date = date.group(1) if date else ""

    body = soup.select_one(".widget-richtext .text") or soup.body or soup
    episode.vocabulary = _parse_vocabulary(body)
    episode.lines = _parse_transcript(body)
    if not episode.lines:
        raise EpisodeError("這一頁找不到逐字稿（TRANSCRIPT）")
    return episode


def _heading_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()).casefold()


def _parse_vocabulary(body: Tag) -> list[tuple[str, str]]:
    heading = next(
        (
            h
            for h in body.find_all(["h3", "h4", "strong"])
            if _heading_text(h) == "vocabulary"
        ),
        None,
    )
    if heading is None:
        return []
    block = heading.find_next("p")
    if block is None:
        return []
    items: list[tuple[str, str]] = []
    word, definition = None, []
    for node in block.descendants:
        if isinstance(node, Tag) and node.name in ("strong", "b"):
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                if word:
                    items.append((word, " ".join(" ".join(definition).split())))
                word, definition = text, []
        elif (
            isinstance(node, NavigableString)
            and word is not None
            and node.find_parent(["strong", "b"]) is None
        ):
            definition.append(str(node).replace("\xa0", " "))
    if word:
        items.append((word, " ".join(" ".join(definition).split())))
    return items


def _is_blank(node) -> bool:
    return (
        isinstance(node, NavigableString) and not str(node).replace("\xa0", " ").strip()
    )


def _is_speaker(node) -> bool:
    """A speaker name is a bold run on a line of its own ("<br><b>Phil</b><br>").
    Bold words inside a sentence (the episode's vocabulary) are not speakers."""
    if not (isinstance(node, Tag) and node.name in ("strong", "b")):
        return False
    if not node.get_text(strip=True).replace("\xa0", ""):
        return False

    def neighbour(step):
        sibling = getattr(node, step)
        while sibling is not None and _is_blank(sibling):
            sibling = getattr(sibling, step)
        return sibling

    before, after = neighbour("previous_sibling"), neighbour("next_sibling")
    on_own_line_before = before is None or (
        isinstance(before, Tag) and before.name == "br"
    )
    on_own_line_after = after is None or (isinstance(after, Tag) and after.name == "br")
    return on_own_line_before and on_own_line_after


def _parse_transcript(body: Tag) -> list[Line]:
    marker = next(
        (
            t
            for t in body.find_all(["strong", "b", "h3", "h4"])
            if _heading_text(t) == "transcript"
        ),
        None,
    )
    if marker is None:
        return []
    start = marker.find_parent("p") or marker

    turns: list[tuple[str, str]] = []
    for paragraph in start.find_all_next("p"):
        speaker, words = None, []
        for node in paragraph.children:
            if _is_speaker(node):
                if speaker is not None and "".join(words).strip():
                    turns.append((speaker, "".join(words)))
                speaker = " ".join(node.get_text(" ", strip=True).split())
                words = []
            elif speaker is not None:
                if isinstance(node, Tag):
                    if node.name == "br":
                        words.append(" ")
                    elif node.name not in ("img", "script"):
                        words.append(node.get_text())
                else:
                    words.append(str(node))
        if speaker is not None and "".join(words).strip():
            turns.append((speaker, "".join(words)))

    lines: list[Line] = []
    for speaker, text in turns:
        text = " ".join(text.replace("\xa0", " ").split())
        for sentence in _SENTENCE_END.split(text):
            sentence = sentence.strip()
            if sentence:
                lines.append(Line(speaker, sentence))
    return lines


# --------------------------------------------------------------------------- matching
def _word_forms(word: str) -> list[str]:
    """Common inflected forms: prime -> primes, primed, priming; stop -> stopped ..."""
    forms = {word, word + "s", word + "es", word + "ed", word + "ing", word + "'s"}
    forms |= set(_IRREGULAR.get(word, "").split())
    if word.endswith("e"):
        forms |= {word + "d", word[:-1] + "ing"}
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        forms |= {word[:-1] + "ies", word[:-1] + "ied"}
    if (
        len(word) >= 3
        and word[-1] not in "aeiouwxy"
        and word[-2] in "aeiou"
        and word[-3] not in "aeiou"
    ):
        forms |= {word + word[-1] + "ed", word + word[-1] + "ing"}
    return sorted(forms, key=len, reverse=True)


def term_pattern(term: str) -> re.Pattern | None:
    """A regex that finds `term` in running text, allowing inflections and
    placeholders such as "prime (something)" or "get the hang of sth"."""
    term = term.casefold().replace("’", "'")
    term = re.sub(r"[()\[\]]", " ", term)
    tokens = [t for t in re.split(r"[\s/]+", term) if t]
    parts: list[str] = []
    for token in tokens:
        if token in _PLACEHOLDERS:
            if parts and parts[-1] != "GAP":
                parts.append("GAP")
            continue
        words = [w for w in re.split(r"-", token) if w]
        if not words:
            continue
        parts.append(
            r"[\s-]?".join(
                "(?:" + "|".join(re.escape(f) for f in _word_forms(w)) + ")"
                for w in words
            )
        )
    while parts and parts[-1] == "GAP":
        parts.pop()
    if not parts:
        return None
    regex, previous = "", None
    for part in parts:
        if part == "GAP":
            regex += r"(?:\W+\w+(?:'\w+)?){0,3}"
        else:
            if previous is not None:
                regex += r"\W+"
            regex += part
        previous = part
    return re.compile(r"(?<![\w'])" + regex + r"(?![\w])", re.IGNORECASE)


@dataclass
class SentenceMatch:
    speaker: str
    sentence: str
    start: int
    end: int

    def html(self) -> str:
        s = self.sentence
        quoted = (
            html.escape(s[: self.start])
            + "<b>"
            + html.escape(s[self.start : self.end])
            + "</b>"
            + html.escape(s[self.end :])
        )
        return f'{quoted} <span class="od-speaker">— {html.escape(self.speaker)}</span>'


def find_sentence(
    episode: Episode, term: str, alternatives: tuple[str, ...] = ()
) -> SentenceMatch | None:
    """The first transcript sentence that uses `term` (or one of `alternatives`,
    e.g. the word Cambridge redirected to). The first use is normally the one in the
    original clip; the recap at the end comes later and only repeats the definition."""
    for candidate in (term, *alternatives):
        pattern = term_pattern(candidate)
        if pattern is None:
            continue
        for line in episode.lines:
            found = pattern.search(line.sentence.replace("’", "'"))
            if found:
                return SentenceMatch(
                    line.speaker, line.sentence, found.start(), found.end()
                )
    return None
