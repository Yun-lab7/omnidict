"""Read a BBC Learning English episode page (6 Minute English, Real Easy English,
Learning English from the News, ...).

From the page we take the title, episode number and date (for the "source" of a card),
the episode's vocabulary list, and the transcript split into sentences, so that each
word can be shown with the sentence it was heard in. Programmes without a transcript
(Learning English from the News) give the news headlines and example sentences instead.

Nothing here touches Qt or the collection, so it can be tested on its own.
"""

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

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
        """e.g. "6min::2026-11-05_Could_vaccines_cure_cancer".

        Anki tags can't contain spaces, so they become "_". The date comes first so
        the episodes are listed in order in the browser's sidebar.
        """
        short = _SHORT_PROGRAMME_NAMES.get(self.programme)
        prefix = short or _tag_part(self.programme) or "bbc"
        name = "_".join(p for p in (_iso_date(self.date), _tag_part(self.title)) if p)
        name = name or self.number
        return f"{prefix}::{name}" if name else ""

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
            f"可找原句的句子 {len(self.lines)} 句）"
        )


# Tag prefixes for programmes whose full name is long.
_SHORT_PROGRAMME_NAMES = {
    "6 Minute English": "6min",
    "Learning English from the News": "news",
    "Real Easy English": "easy",
}
# Speaker shown for an example sentence from the page's word list (not the programme).
EXAMPLE_SPEAKER = "Example"


_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=1,
    )
}


def _iso_date(text: str) -> str:
    """ "05 Nov 2026" -> "2026-11-05" (no locale involved); "" if it can't be read."""
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(\d{4})$", text.strip())
    if not match or match.group(2).lower() not in _MONTHS:
        return ""
    day, month, year = match.groups()
    return f"{year}-{_MONTHS[month.lower()]:02d}-{int(day):02d}"


def _tag_part(text: str) -> str:
    """ "Could vaccines cure cancer?" -> "Could_vaccines_cure_cancer"."""
    # Apostrophes and dots in abbreviations join the word: "U.K.'s" -> "UKs".
    text = re.sub(r"['’.]", "", text)
    return "_".join(re.findall(r"[^\W_]+", text))


class EpisodeError(RuntimeError):
    pass


def _host(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return ""
    return (parts.hostname or "").lower()


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def is_bbc(url: str) -> bool:
    host = _host(url)
    return _host_is(host, "bbc.co.uk") or host == "bbc.in"


def is_youtube(url: str) -> bool:
    host = _host(url)
    return _host_is(host, "youtube.com") or host == "youtu.be"


def check_url(url: str) -> str:
    url = url.strip()
    if not (is_bbc(url) or is_youtube(url)):
        raise EpisodeError(
            "請貼 BBC Learning English 的節目網址（bbc.co.uk/learningenglish/…）"
            "或這一集的 YouTube 網址"
        )
    return url


_BBC_SHORT_LINK = re.compile(r"https?://bbc\.in/[A-Za-z0-9]+")
_BBC_EPISODE_LINK = re.compile(
    r"https?://(?:www\.)?bbc\.co\.uk/learningenglish/[A-Za-z0-9_/-]*?/ep-[A-Za-z0-9-]+"
)
# Episodes of other programmes: ".../features/real-easy-english/261030".
_BBC_FEATURE_LINK = re.compile(
    r"https?://(?:www\.)?bbc\.co\.uk/learningenglish/(?:[a-z]+/)?features/"
    r"[A-Za-z0-9_-]+/\d{6}\b"
)


def find_bbc_link(page: str) -> str | None:
    """The BBC episode link in a YouTube page's description.

    BBC Learning English videos say "Find a free worksheet, transcript and quiz for
    this episode here 👉 https://bbc.in/…". Other BBC links in the description (the
    newsletter, the home page) are not episode links and are ignored.
    """
    # The description sits in JSON ("https:\/\/bbc.in\/…") and in YouTube redirect
    # links ("q=https%3A%2F%2Fbbc.in%2F…"); undo both before searching.
    text = page.replace("\\/", "/").replace("\\u0026", "&")
    text = unquote(text)
    for pattern in (_BBC_SHORT_LINK, _BBC_EPISODE_LINK, _BBC_FEATURE_LINK):
        found = pattern.search(text)
        if found:
            return found.group(0)
    return None


def _looks_like_youtube(page: str, saved_from: str) -> bool:
    # A BBC page has the "widget-richtext" body; some (the news programme) have no
    # transcript, so "TRANSCRIPT" alone doesn't tell them apart.
    return is_youtube(saved_from) or (
        not saved_from
        and "youtube.com" in page[:5000]
        and "widget-richtext" not in page
        and "TRANSCRIPT" not in page
    )


def _without_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def load_episode(source: str, fetch) -> Episode:
    """`source` is an episode URL (BBC or YouTube), or a page saved with Ctrl+S.

    `fetch(url) -> (final_url, html)` downloads a page following redirects; it is
    passed in so tests need no network.
    """
    source = source.strip().strip('"')
    path = Path(source)
    if not source.lower().startswith(("http://", "https://")) and path.is_file():
        page = path.read_text(encoding="utf-8", errors="replace")
        saved_from = re.search(r"saved from url=\(\d+\)(\S+)", page[:500])
        saved_url = saved_from.group(1) if saved_from else ""
        if _looks_like_youtube(page, saved_url):
            return _load_from_youtube_page(page, fetch)
        return parse_episode(page, saved_url)

    url = check_url(source)
    if is_youtube(url):
        _final, page = fetch(url)
        return _load_from_youtube_page(page, fetch)
    return _load_bbc(url, fetch)


def _load_from_youtube_page(page: str, fetch) -> Episode:
    link = find_bbc_link(page)
    if link is None:
        raise EpisodeError(
            "這支 YouTube 影片的簡介裡找不到 BBC 的節目連結，請改貼 BBC 網址"
        )
    return _load_bbc(link, fetch)


def _load_bbc(url: str, fetch) -> Episode:
    final_url, page = fetch(url)
    final_url = final_url or url
    if not _host_is(_host(final_url), "bbc.co.uk"):
        raise EpisodeError(f"連結沒有轉到 BBC 的網站：{final_url}")
    return parse_episode(page, _without_query(final_url))


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
    episode.vocabulary, examples = _parse_vocabulary(body)
    # The programme's own words come first: the transcript, or for the news
    # programme the headlines the words were taken from.
    lines = _parse_transcript(body) or _parse_headlines(body)
    lines += [Line(EXAMPLE_SPEAKER, sentence) for sentence in examples]
    episode.lines = lines
    if not episode.lines:
        raise EpisodeError("這一頁找不到逐字稿（TRANSCRIPT）或例句")
    return episode


def _heading_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()).casefold()


def _find_section(body: Tag, names: tuple[str, ...]) -> Tag | None:
    """The block that starts a section, e.g. "<h3>Vocabulary</h3>" or
    "<p><strong>TRANSCRIPT</strong></p>"."""
    for tag in body.find_all(["h3", "h4", "strong", "b"]):
        if _heading_text(tag) in names:
            if tag.name in ("strong", "b"):
                return tag.find_parent(["h3", "h4", "p"]) or tag
            return tag
    return None


def _is_section_start(tag: Tag) -> bool:
    """A heading, or a paragraph that is only a bold title ("<p><strong>Next</strong></p>")."""
    if tag.name in ("h2", "h3", "h4"):
        return True
    if tag.name != "p":
        return False
    text = _heading_text(tag)
    return bool(text) and any(
        _heading_text(b) == text for b in tag.find_all(["strong", "b"])
    )


def _section_blocks(start: Tag):
    """The elements after a section's heading, up to the next section."""
    for sibling in start.find_next_siblings():
        if _is_section_start(sibling):
            return
        yield sibling


def _parse_vocabulary(body: Tag) -> tuple[list[tuple[str, str]], list[str]]:
    """The word list and its example sentences.

    Words are bold, each followed by its definition. They are all in one paragraph
    (6 Minute English), one paragraph each (Real Easy English), or one paragraph each
    with a list of example sentences after it (Learning English from the News).
    """
    heading = _find_section(body, ("vocabulary", "key words and phrases"))
    if heading is None:
        return [], []
    blocks: list[Tag] = []
    for block in _section_blocks(heading):
        if block.name in ("ul", "ol"):
            blocks.append(block)
        elif not _heading_text(block):
            continue  # an image or an empty line
        elif _starts_with_bold(block):
            blocks.append(block)
        else:
            break  # ordinary text: the word list is over
    if not any(b.name not in ("ul", "ol") for b in blocks):
        # The heading isn't next to the words (e.g. wrapped in a <div>).
        first = heading.find_next("p")
        blocks = [first] if first is not None else []

    items: list[tuple[str, str]] = []
    examples: list[str] = []
    word, definition = None, []
    for block in blocks:
        if block.name in ("ul", "ol"):
            for item in block.find_all("li"):
                text = " ".join(item.get_text().replace("\xa0", " ").split())
                if text:
                    examples.append(text)
            continue
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
    return items, examples


def _starts_with_bold(block: Tag) -> bool:
    first = next((n for n in block.children if not _is_blank(n)), None)
    return (
        isinstance(first, Tag)
        and first.name in ("strong", "b")
        and bool(first.get_text(strip=True))
    )


def _parse_headlines(body: Tag) -> list[Line]:
    """News headlines, each followed by its publication in bold on the next line:
    "<p>Britain <strong>on alert</strong> as …<br><strong>The Telegraph</strong></p>"."""
    heading = _find_section(body, ("news headlines",))
    if heading is None:
        return []
    lines: list[Line] = []
    for block in _section_blocks(heading):
        if block.name != "p":
            continue
        parts: list[list] = [[]]
        for node in block.children:
            if isinstance(node, Tag) and node.name == "br":
                parts.append([])
            else:
                parts[-1].append(node)

        def text(nodes):
            return " ".join(
                "".join(n.get_text() if isinstance(n, Tag) else str(n) for n in nodes)
                .replace("\xa0", " ")
                .split()
            )

        parts = [p for p in parts if text(p)]
        if not parts:
            continue
        source = ""
        last = [n for n in parts[-1] if not _is_blank(n)]
        if len(parts) > 1 and all(
            isinstance(n, Tag) and n.name in ("strong", "b") for n in last
        ):
            source = text(parts.pop())
        headline = " ".join(text(p) for p in parts)
        if headline:
            lines.append(Line(source or "Headline", headline))
    return lines


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
    start = _find_section(body, ("transcript",))
    if start is None:
        return []

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
        return self._with_speaker(quoted)

    def cloze_html(self) -> str:
        """The sentence with the word hidden, for a Cloze note: "a way of {{c1::priming}} …"."""

        def plain(text: str) -> str:
            # Braces and "::" in the text would confuse Anki's cloze syntax.
            text = text.replace("{", "(").replace("}", ")").replace("::", ": :")
            return html.escape(text)

        s = self.sentence
        quoted = (
            plain(s[: self.start])
            + "{{c1::"
            + plain(s[self.start : self.end])
            + "}}"
            + plain(s[self.end :])
        )
        return self._with_speaker(quoted)

    def _with_speaker(self, quoted: str) -> str:
        if not self.speaker:
            return quoted
        return f'{quoted} <span class="od-speaker">— {html.escape(self.speaker)}</span>'


def find_sentence(
    episode: Episode, term: str, alternatives: tuple[str, ...] = ()
) -> SentenceMatch | None:
    """The first transcript sentence that uses `term` (or one of `alternatives`,
    e.g. the word Cambridge redirected to). The first use is normally the one in the
    original clip; the recap at the end comes later and only repeats the definition."""
    return find_in_lines(episode.lines, term, alternatives)


def find_in_lines(
    lines: list[Line], term: str, alternatives: tuple[str, ...] = ()
) -> SentenceMatch | None:
    """The first of `lines` that uses `term` (or one of `alternatives`)."""
    for candidate in (term, *alternatives):
        pattern = term_pattern(candidate)
        if pattern is None:
            continue
        for line in lines:
            found = pattern.search(line.sentence.replace("’", "'"))
            if found:
                return SentenceMatch(
                    line.speaker, line.sentence, found.start(), found.end()
                )
    return None
