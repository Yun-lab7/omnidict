from pathlib import Path

import pytest

from omnidict.bbc import (
    EpisodeError,
    check_url,
    find_bbc_link,
    find_sentence,
    load_episode,
    parse_episode,
    term_pattern,
)

# A made-up page with the same structure as a BBC Learning English episode page.
SAMPLE = """<!DOCTYPE html>
<!-- saved from url=(0080)https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2026/ep-990101 -->
<html><head><title>BBC Learning English - 6 Minute English / Do cats like music?</title></head>
<body><div id="bbcle-content">
<div class="widget widget-bbcle-featuresubheader"><div class="text"><div class="details">
<h3><b>Episode 990101</b> / 01 Jan 2099</h3></div></div></div>
<div class="widget widget-richtext 6"><div class="text" dir="ltr">
<h3>Vocabulary</h3>
<p><strong>tune in</strong><br>start listening<br>&nbsp;<br><strong>get the hang of (something)</strong><br>learn how to do it<br><strong>&nbsp;</strong><br><strong>purr</strong><br>the sound a happy cat makes</p>
<p><strong style="font-size: 1.17em;">TRANSCRIPT</strong></p>
<p class="p2">Note: This is not a word-for-word transcript.</p>
<p><strong>Amy</strong><br>Hello and thanks for tuning in. Today: cats!<br>&nbsp;<br>
<strong>Ben</strong><br>My cat finally got the hang of the cat flap. She <strong>purrs</strong> at Mozart, too.<br>&nbsp;<br>
<strong>Dr Lee</strong><br>Cats can’t carry a tune, but they’re carrying on purring.<br><br>
<a href="x"><img src="y"></a></p>
<p><strong>Amy</strong><br>If you purr, you make a soft sound. Bye!</p>
<p>What do you think of the new version? Email us.</p>
<p>Next</p>
</div></div></div></body></html>"""

REAL_PAGE = Path(__file__).parent / "bbc_pages" / "ep-261105.html"


def test_parse_sample_details():
    ep = parse_episode(SAMPLE, "https://www.bbc.co.uk/x")
    assert (ep.programme, ep.title, ep.number, ep.date) == (
        "6 Minute English",
        "Do cats like music?",
        "990101",
        "01 Jan 2099",
    )
    assert ep.tag == "6min::2099-01-01_Do_cats_like_music"
    assert ep.vocabulary == [
        ("tune in", "start listening"),
        ("get the hang of (something)", "learn how to do it"),
        ("purr", "the sound a happy cat makes"),
    ]
    assert (
        '<a href="https://www.bbc.co.uk/x">6 Minute English · Do cats like music?</a>'
        in (ep.source_html())
    )


def test_parse_sample_transcript():
    ep = parse_episode(SAMPLE)
    assert [(line.speaker, line.sentence) for line in ep.lines] == [
        ("Amy", "Hello and thanks for tuning in."),
        ("Amy", "Today: cats!"),
        ("Ben", "My cat finally got the hang of the cat flap."),
        ("Ben", "She purrs at Mozart, too."),  # bold word inside a sentence
        ("Dr Lee", "Cats can’t carry a tune, but they’re carrying on purring."),
        ("Amy", "If you purr, you make a soft sound."),
        ("Amy", "Bye!"),
    ]


def test_find_sentence_forms_and_phrases():
    ep = parse_episode(SAMPLE)

    def found(term, *alts):
        match = find_sentence(ep, term, alts)
        return match and match.sentence[match.start : match.end]

    assert found("tune in") == "tuning in"
    assert found("get the hang of (something)") == "got the hang of"
    assert found("purr") == "purrs"  # first use, not the recap
    assert found("carry on") == "carrying on"
    assert found("can't") == "can’t"
    assert found("dog") is None
    assert found("woof", "purr") == "purrs"  # e.g. the word Cambridge redirected to
    html = find_sentence(ep, "purr").html()
    assert (
        html == 'She <b>purrs</b> at Mozart, too. <span class="od-speaker">— Ben</span>'
    )


def test_term_pattern_details():
    assert term_pattern("(something)") is None
    assert term_pattern("prime (something)").search("a way of priming the system")
    assert term_pattern("stop").search("we stopped")
    assert term_pattern("study").search("she studied")
    assert term_pattern("well-known").search("a well known face")
    assert not term_pattern("cat").search("category")
    assert term_pattern("put sth off").search("I put the meeting off")
    assert term_pattern("take off").search("the plane took off")
    assert term_pattern("break down").search("my car broke down")


BBC_URL = "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2099/ep-990101"

# What a YouTube watch page looks like to a plain download: the description is in a
# JSON blob, with escaped slashes, next to other BBC links that are not the episode.
YOUTUBE_RAW = (
    "<html><head><title>Do cats like music? ⏲️ 6 Minute English - YouTube</title></head>"
    '<body><script>var ytInitialPlayerResponse = {"videoDetails":{"shortDescription":'
    '"Subscribe to our newsletter 👉\\nhttps:\\/\\/www.bbc.co.uk\\/send\\/u178220599'
    "\\nFind a free worksheet, transcript and quiz for this episode here 👉\\n"
    'https:\\/\\/bbc.in\\/4BHgdjN\\nVisit https:\\/\\/www.bbc.co.uk\\/learningenglish"}};'
    "</script></body></html>"
)
# The same page saved from a browser: links go through YouTube's redirect.
YOUTUBE_SAVED = (
    "<!-- saved from url=(0043)https://www.youtube.com/watch?v=-ukHyqiEH1U -->"
    '<html><body><a href="https://www.youtube.com/redirect?event=video_description'
    '&amp;q=https%3A%2F%2Fbbc.in%2F4BHgdjN&amp;v=x">https://bbc.in/4BHgdjN</a></body></html>'
)


def fake_web(pages):
    """fetch(url) -> (final_url, html); bbc.in links redirect to BBC_URL with a query."""
    calls = []

    def fetch(url):
        calls.append(url)
        if url.startswith("https://bbc.in/"):
            return BBC_URL + "?utm_source=youtube", pages[BBC_URL]
        return url, pages[url]

    fetch.calls = calls
    return fetch


def test_load_episode_from_bbc_url_and_file(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(SAMPLE, encoding="utf-8")
    ep = load_episode(f'"{page}"', fetch=None)
    assert ep.url.endswith("ep-990101")

    fetch = fake_web({BBC_URL: SAMPLE})
    ep = load_episode(BBC_URL, fetch)
    assert fetch.calls == [BBC_URL] and ep.url == BBC_URL

    for bad in (
        "https://evil.example/ep",
        "ftp://www.bbc.co.uk/x",
        "https://bbc.co.uk.evil.com/",
        "https://notyoutube.com/watch?v=x",
    ):
        with pytest.raises(EpisodeError):
            check_url(bad)
    with pytest.raises(EpisodeError):
        parse_episode("<html><title>x</title><p>no transcript</p></html>")


def test_find_bbc_link():
    assert find_bbc_link(YOUTUBE_RAW) == "https://bbc.in/4BHgdjN"
    assert find_bbc_link(YOUTUBE_SAVED) == "https://bbc.in/4BHgdjN"
    assert find_bbc_link(f"see {BBC_URL} now") == BBC_URL
    # newsletter and home page are not episode links
    assert (
        find_bbc_link(
            "https://www.bbc.co.uk/send/u1 https://www.bbc.co.uk/learningenglish"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=-ukHyqiEH1U",
        "https://youtu.be/-ukHyqiEH1U",
        "https://m.youtube.com/watch?v=-ukHyqiEH1U&t=30s",
    ],
)
def test_load_episode_from_youtube_url(url):
    fetch = fake_web({url: YOUTUBE_RAW, BBC_URL: SAMPLE})
    ep = load_episode(url, fetch)
    assert fetch.calls == [url, "https://bbc.in/4BHgdjN"]
    assert ep.url == BBC_URL  # query string from the redirect removed
    assert ep.title == "Do cats like music?"


def test_load_episode_from_saved_youtube_page(tmp_path):
    page = tmp_path / "yt.html"
    page.write_text(YOUTUBE_SAVED, encoding="utf-8")
    fetch = fake_web({BBC_URL: SAMPLE})
    ep = load_episode(str(page), fetch)
    assert ep.number == "990101" and fetch.calls == ["https://bbc.in/4BHgdjN"]


def test_youtube_without_bbc_link_or_redirect_elsewhere():
    url = "https://www.youtube.com/watch?v=abc"
    with pytest.raises(EpisodeError, match="找不到 BBC"):
        load_episode(url, fake_web({url: "<html>cat video</html>"}))

    def to_elsewhere(u):
        return (
            ("https://evil.example/", "<html></html>")
            if "bbc.in" in u
            else (u, YOUTUBE_RAW)
        )

    with pytest.raises(EpisodeError, match="沒有轉到 BBC"):
        load_episode(url, to_elsewhere)


@pytest.mark.skipif(not REAL_PAGE.exists(), reason="saved BBC page not present")
def test_real_episode_261105():
    ep = load_episode(str(REAL_PAGE), fetch=None)
    assert ep.title == "Could vaccines cure cancer?"
    assert (ep.number, ep.date) == ("261105", "05 Nov 2026")
    assert ep.tag == "6min::2026-11-05_Could_vaccines_cure_cancer"
    assert [w for w, _ in ep.vocabulary] == [
        "a long time coming",
        "false dawn",
        "space",
        "breakthrough",
        "prime (something)",
        "promise",
    ]
    assert {line.speaker for line in ep.lines} == {
        "Georgie",
        "Phil",
        "Tom Whipple",
        "Anne Willis",
    }
    expected = {
        "a long time coming": ("Tom Whipple", "a long time coming"),
        "false dawn": ("Tom Whipple", "false dawns"),
        "space": ("Anne Willis", "space"),
        "breakthrough": ("Anne Willis", "breakthrough"),
        "prime (something)": ("Anne Willis", "priming"),
        "promise": ("Anne Willis", "promise"),
    }
    for word, (speaker, text) in expected.items():
        match = find_sentence(ep, word)
        assert match is not None, word
        assert (match.speaker, match.sentence[match.start : match.end]) == (
            speaker,
            text,
        )


# Made-up pages with the structure of the other programmes.
REAL_EASY_SAMPLE = """<html><head><title>BBC Learning English - Real Easy English / Talking about cats</title></head>
<body><div class="widget widget-bbcle-featuresubheader"><div class="text"><div class="details">
<h3><b>Episode 990102</b> / 02 Jan 2099</h3></div></div></div>
<div class="widget widget-richtext 6"><div class="text" dir="ltr">
<h3>Introduction</h3><p>Amy and Ben talk about <strong>cats</strong>.</p>
<h3>Vocabulary</h3>
<p><strong>whisker<br></strong>long hair on a cat's face</p>
<p><strong>tabby</strong><br>a cat with stripes</p>
<p><a href="x"><img src="y"></a></p>
<h3>Transcript</h3>
<p><strong>Amy</strong><br>My cat is a <strong>tabby</strong>.<br> <br><strong>Ben</strong><br>Mine has white <strong>whiskers</strong>.<strong><br></strong><strong> </strong><br><strong>Amy</strong><br>Bye!</p>
<h3>Now try this...</h3><p>Watch <a href="z"><strong>more</strong></a>.</p>
</div></div></body></html>"""

NEWS_SAMPLE = """<html><head><title>BBC Learning English - Learning English from the News / Cats rule the internet</title></head>
<body><div class="widget widget-bbcle-featuresubheader"><div class="text"><div class="details">
<h3><b>Episode 990103</b> / 03 Jan 2099</h3></div></div></div>
<div class="widget widget-richtext 6"><div class="text" dir="ltr">
<p><strong style="font-size: 1.17em;">The story</strong></p><p>Cats are popular online.</p>
<h3>News headlines </h3>
<p>Cat videos <strong>take over</strong> social media <br><strong>The Daily Paws</strong></p>
<p>Why are cat pictures so <strong>irresistible</strong>?<br><strong>Cat News</strong></p>
<p><a href="w"><strong><img src="y"></strong></a></p>
<h3><strong style="font-size: 1.17em;">Key words and phrases</strong></h3>
<p><strong>take over<br></strong>get control of something</p>
<ul><li>The weeds have <strong>taken over</strong> my garden.</li></ul>
<p><strong>irresistible</strong><br>too attractive to refuse</p>
<ul><li>The cake was <strong>irresistible</strong>.</li></ul>
<p><strong>purr</strong><br>the sound a happy cat makes</p>
<ul><li>My cat <strong>purrs</strong> on my lap.</li></ul>
<p><a href="v"><strong><img src="y"><br></strong></a></p>
<p><strong style="font-size: 1.17em;">Next</strong></p>
<p>Find <a href="u"><strong>more programmes here</strong></a>.</p>
</div></div></body></html>"""


def test_parse_real_easy_sample():
    ep = parse_episode(REAL_EASY_SAMPLE)
    assert ep.tag == "easy::2099-01-02_Talking_about_cats"
    # one paragraph per word; bold words in the introduction are not vocabulary
    assert ep.vocabulary == [
        ("whisker", "long hair on a cat's face"),
        ("tabby", "a cat with stripes"),
    ]
    assert [(line.speaker, line.sentence) for line in ep.lines] == [
        ("Amy", "My cat is a tabby."),
        ("Ben", "Mine has white whiskers."),
        ("Amy", "Bye!"),
    ]


def test_parse_news_sample_without_transcript():
    ep = parse_episode(NEWS_SAMPLE)
    assert ep.tag == "news::2099-01-03_Cats_rule_the_internet"
    assert ep.vocabulary == [
        ("take over", "get control of something"),
        ("irresistible", "too attractive to refuse"),
        ("purr", "the sound a happy cat makes"),
    ]
    assert [(line.speaker, line.sentence) for line in ep.lines] == [
        ("The Daily Paws", "Cat videos take over social media"),
        ("Cat News", "Why are cat pictures so irresistible?"),
        ("Example", "The weeds have taken over my garden."),
        ("Example", "The cake was irresistible."),
        ("Example", "My cat purrs on my lap."),
    ]
    # the headline comes before the example sentence; a word missing from the
    # headlines falls back to its example
    assert find_sentence(ep, "take over").speaker == "The Daily Paws"
    assert find_sentence(ep, "purr").speaker == "Example"


def test_saved_news_page_is_not_taken_for_youtube(tmp_path):
    page = tmp_path / "news.html"
    # no "saved from" comment, a YouTube link near the top, and no transcript
    page.write_text(
        NEWS_SAMPLE.replace(
            "<body>", '<body><a href="https://www.youtube.com/x">yt</a>'
        ),
        encoding="utf-8",
    )
    ep = load_episode(str(page), fetch=None)
    assert ep.title == "Cats rule the internet"


def test_find_bbc_link_for_other_programmes():
    url = "https://www.bbc.co.uk/learningenglish/english/features/real-easy-english/261030"
    assert find_bbc_link(f"episode: {url}\\n") == url
    # the programme's index page is not an episode
    assert (
        find_bbc_link(
            "https://www.bbc.co.uk/learningenglish/english/features/real-easy-english"
        )
        is None
    )


REAL_EASY_PAGE = Path(__file__).parent / "bbc_pages" / "real-easy-261030.html"
NEWS_PAGE = Path(__file__).parent / "bbc_pages" / "news-261104.html"


@pytest.mark.skipif(not REAL_EASY_PAGE.exists(), reason="saved BBC page not present")
def test_real_real_easy_261030():
    ep = load_episode(str(REAL_EASY_PAGE), fetch=None)
    assert ep.tag == "easy::2026-10-30_Talking_about_the_ocean"
    assert [w for w, _ in ep.vocabulary] == [
        "octopus",
        "threat",
        "pollution",
        "single-use plastic",
    ]
    for word, text in {
        "octopus": "octopuses",
        "threat": "threats",
        "pollution": "pollution",
        "single-use plastic": "single-use plastic",
    }.items():
        match = find_sentence(ep, word)
        assert match is not None, word
        assert match.speaker == "Becca"
        assert match.sentence[match.start : match.end] == text


@pytest.mark.skipif(not NEWS_PAGE.exists(), reason="saved BBC page not present")
def test_real_news_261104():
    ep = load_episode(str(NEWS_PAGE), fetch=None)
    assert ep.tag == "news::2026-11-04_Cyber_attacks_on_shops"
    assert [w for w, _ in ep.vocabulary] == ["on alert", "spoiled", "vulnerable"]
    assert {w: find_sentence(ep, w).speaker for w, _ in ep.vocabulary} == {
        "on alert": "The Telegraph",
        "spoiled": "CBC",
        "vulnerable": "BBC News",
    }


def test_tag_formats():
    from omnidict.bbc import Episode

    ep = Episode(
        url="",
        programme="6 Minute English",
        title="What’s the U.K.'s best café?",
        date="1 Sept 2026",
    )
    assert ep.tag == "6min::2026-09-01_Whats_the_UKs_best_café"
    assert Episode(
        url="", programme="The English We Speak", title="Spill the tea"
    ).tag == ("The_English_We_Speak::Spill_the_tea")
    assert (
        Episode(url="", programme="6 Minute English", number="261105").tag
        == "6min::261105"
    )
    assert Episode(url="").tag == ""


def test_vocabulary_ends_at_ordinary_text():
    page = """<html><head><title>BBC Learning English - X / Y</title></head><body>
<div class="widget widget-richtext"><div class="text">
<h3>Vocabulary</h3>
<p><strong>prime</strong><br>get ready</p>
<p><a href="q"><img src="i"></a></p>
<p><strong>stall</strong><br>stop</p>
<p>This week's quiz answer is below.</p>
<p>Find <a href="u"><strong>more programmes here</strong></a>.</p>
<p><strong>TRANSCRIPT</strong></p>
<p><strong>Amy</strong><br>We primed it.</p>
</div></div></body></html>"""
    ep = parse_episode(page)
    assert ep.vocabulary == [("prime", "get ready"), ("stall", "stop")]


def test_vocabulary_heading_wrapped_in_a_div():
    page = """<html><body><div class="widget widget-richtext"><div class="text">
<div><h3>Vocabulary</h3></div>
<p><strong>prime</strong><br>get ready<br><strong>stall</strong><br>stop</p>
<p><strong>TRANSCRIPT</strong></p>
<p><strong>Amy</strong><br>We primed it.</p>
</div></div></body></html>"""
    assert [w for w, _ in parse_episode(page).vocabulary] == ["prime", "stall"]
