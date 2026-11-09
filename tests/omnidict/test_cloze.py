from omnidict.bbc import parse_episode
from omnidict.cloze import (
    build_sentence,
    cloze_existing,
    episode_definition,
    fill_cloze_note,
    has_cloze,
    mask_word,
    move_speaker_to_source,
    with_speaker,
)
from omnidict.provider.common import (
    Definition,
    Entry,
    Example,
    Pronunciation,
    Sense,
)
from omnidict.quickadd import example_sentences, find_field_indices, plain_hint

from .test_bbc import SAMPLE

EXAMPLES = [
    "The kids are tuning in to the radio.",
    "My cat purred loudly.",
]


def test_build_sentence_prefers_the_episode():
    ep = parse_episode(SAMPLE)
    sentence = build_sentence("purr", "purr", ep, EXAMPLES, "Cambridge", cloze=True)
    assert sentence.origin == "episode"
    # the speaker is kept out of the sentence, which is read aloud
    assert (sentence.html, sentence.speaker) == (
        "She {{c1::purrs}} at Mozart, too.",
        "Ben",
    )
    # not a cloze note type: the word is bold instead
    bold = build_sentence("purr", "purr", ep, EXAMPLES, "Cambridge", cloze=False)
    assert "<b>purrs</b>" in bold.html and "{{c1::" not in bold.html


def test_build_sentence_falls_back_to_dictionary_examples():
    ep = parse_episode(SAMPLE)
    # "purred" isn't in the episode; neither is "loudly" -> dictionary example
    sentence = build_sentence(
        "loudly", "loudly", ep, ["He sang loudly."], "Cambridge", cloze=True
    )
    assert sentence.origin == "dictionary"
    assert (sentence.html, sentence.speaker) == (
        "He sang {{c1::loudly}}.",
        "Cambridge",
    )
    # no episode at all (a plain word list)
    sentence = build_sentence("purr", "purr", None, EXAMPLES, "Cambridge", cloze=True)
    assert sentence.origin == "dictionary"
    assert sentence.html.startswith("My cat {{c1::purred}} loudly.")
    # the word Cambridge redirected to is searched too
    sentence = build_sentence(
        "purring", "purr", None, EXAMPLES, "Cambridge", cloze=True
    )
    assert "{{c1::purred}}" in sentence.html


def test_build_sentence_without_any_sentence():
    sentence = build_sentence("woof", "woof", None, EXAMPLES, "Cambridge", cloze=True)
    assert (sentence.origin, sentence.html) == ("word", "{{c1::woof}}")
    assert build_sentence("woof", "woof", None, EXAMPLES, "C", cloze=False) is None


def test_cloze_text_is_escaped_and_safe():
    sentence = build_sentence(
        "fish", "fish", None, ["Fish & chips <3 :: fish}}"], "C", cloze=True
    )
    assert sentence.html.startswith("{{c1::Fish}} &amp; chips &lt;3 : : fish))")
    assert has_cloze(sentence.html)
    assert not has_cloze("no cloze {{c::x}}")


def test_mask_word_and_episode_definition():
    assert mask_word("to purr or not", "purr") == "to ___ or not"
    assert mask_word("get (something) ready", "prime (something)") == (
        "get (something) ready"
    )
    assert mask_word("someone who primes things", "prime (something)") == (
        "someone who ___ things"
    )
    ep = parse_episode(SAMPLE)
    assert episode_definition(ep, "Tune In") == "start listening"
    assert episode_definition(ep, "nope") == ""
    assert episode_definition(None, "purr") == ""


def test_cloze_existing_skips_html_tags():
    text = '<a href="purr.html">My cat</a> purrs a lot'
    assert cloze_existing(text, "purr") == (
        '<a href="purr.html">My cat</a> {{c1::purrs}} a lot'
    )
    assert cloze_existing("nothing here", "purr") is None
    assert cloze_existing("It’s a cat-flap", "it's") == "{{c1::It’s}} a cat-flap"


NAMES = ["Text", "Word", "Hint", "Definition", "Source"]


def test_fill_cloze_note_empty_sentence_gets_an_example():
    fields = ["", "purr", "", "<b>def</b>", ""]
    problem = fill_cloze_note(
        fields,
        NAMES,
        "purr",
        "purr",
        "(of a cat) to purr softly",
        EXAMPLES,
        "Cambridge",
    )
    assert problem is None
    assert fields[0] == "My cat {{c1::purred}} loudly."
    assert fields[4] == '<span class="od-speaker">Cambridge</span>'
    assert fields[2] == "(of a cat) to ___ softly"


def test_fill_cloze_note_typed_sentence():
    fields = ["I heard it purring.", "purr", "my own hint", "", ""]
    assert fill_cloze_note(fields, NAMES, "purr", "purr", "x", [], "C") is None
    assert fields[0] == "I heard it {{c1::purring}}."
    assert fields[2] == "my own hint"  # never overwritten

    already = ["I {{c1::heard}} it.", "purr", "", "", ""]
    assert fill_cloze_note(already, NAMES, "purr", "purr", "", [], "C") is None
    assert already[0] == "I {{c1::heard}} it."

    missing = ["A dog barked.", "purr", "", "", ""]
    problem = fill_cloze_note(missing, NAMES, "purr", "purr", "", [], "C")
    assert problem and "找不到「purr」" in problem
    assert missing[0] == "A dog barked."


def test_field_guessing_for_the_cloze_note_type():
    assert find_field_indices(NAMES, None) == (1, 3)
    # Anki's own Cloze type: no Word field, the old defaults
    assert find_field_indices(["Text", "Back Extra"], None) == (0, 1)


def test_plain_hint_and_examples_from_a_definition():
    definition = Definition(
        entries=[
            Entry(
                headword="purr",
                pronunciations=[Pronunciation(region="UK", audio_file_name="a.mp3")],
                senses=[
                    Sense(
                        "(of a cat)  to make a soft low sound:",
                        examples=[Example("The cat purred."), Example("  ")],
                    ),
                    Sense("to speak softly", examples=[Example("She purred.")]),
                ],
            )
        ]
    )
    assert plain_hint(definition) == "(of a cat) to make a soft low sound"
    assert example_sentences(definition) == ["The cat purred.", "She purred."]
    assert plain_hint(Definition(entries=[])) == ""


def test_cloze_existing_with_entities():
    assert cloze_existing("We had to break&nbsp;the ice first.", "break the ice") == (
        "We had to {{c1::break&nbsp;the ice}} first."
    )
    assert cloze_existing("I like rock &amp; roll.", "rock & roll") == (
        "I like {{c1::rock &amp; roll}}."
    )
    assert mask_word("don’t stop", "don't") == "___ stop"


def test_speaker_goes_with_the_source():
    assert with_speaker("<a href=x>6 Minute English</a>", "Becca") == (
        '<span class="od-speaker">Becca</span> · <a href=x>6 Minute English</a>'
    )
    assert with_speaker("<a>x</a>", "") == "<a>x</a>"
    assert with_speaker("", "Cambridge") == '<span class="od-speaker">Cambridge</span>'
    # notes made by the previous version had the speaker inside the sentence
    old_text = 'I {{c1::love}} it. <span class="od-speaker">— Tom &amp; Jo</span>'
    assert move_speaker_to_source(old_text, "<a>ep</a>") == (
        "I {{c1::love}} it.",
        '<span class="od-speaker">Tom &amp; Jo</span> · <a>ep</a>',
    )
    assert move_speaker_to_source("I {{c1::love}} it.", "") is None
