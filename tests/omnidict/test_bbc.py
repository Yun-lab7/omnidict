from pathlib import Path

import pytest

from omnidict.bbc import (
    EpisodeError,
    check_url,
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
    assert ep.tag == "6min::990101"
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


def test_load_episode_url_and_file(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(SAMPLE, encoding="utf-8")
    ep = load_episode(f'"{page}"', fetch_text=None)
    assert ep.url.endswith("ep-990101")

    fetched = []
    url = "https://www.bbc.co.uk/learningenglish/english/features/x/ep-1"
    ep = load_episode(url, lambda u: fetched.append(u) or SAMPLE)
    assert fetched == [url] and ep.url == url

    for bad in (
        "https://evil.example/ep",
        "ftp://www.bbc.co.uk/x",
        "https://bbc.co.uk.evil.com/",
    ):
        with pytest.raises(EpisodeError):
            check_url(bad)
    with pytest.raises(EpisodeError):
        parse_episode("<html><title>x</title><p>no transcript</p></html>")


@pytest.mark.skipif(not REAL_PAGE.exists(), reason="saved BBC page not present")
def test_real_episode_261105():
    ep = load_episode(str(REAL_PAGE), fetch_text=None)
    assert ep.title == "Could vaccines cure cancer?"
    assert (ep.number, ep.date, ep.tag) == ("261105", "05 Nov 2026", "6min::261105")
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
