"""The cloze note type in a real (temporary) Anki collection."""

from anki.collection import Collection
from anki.consts import MODEL_CLOZE
from anki.sound import TTSTag

from omnidict.batch import ensure_cloze_notetype, upgrade_cloze_notetype
from omnidict.cloze import (
    CLOZE_CSS,
    CLOZE_FIELDS,
    CLOZE_FRONT,
    CLOZE_NOTETYPE_NAME,
    OLD_CLOZE_BACKS,
)


def _add(col, notetype_id, **fields):
    note = col.new_note(col.models.get(notetype_id))
    for name, value in fields.items():
        note[name] = value
    col.add_note(note, col.decks.id("Default"))
    return note


def test_sentence_is_read_aloud_on_the_back_only(tmp_path):
    col = Collection(str(tmp_path / "c.anki2"))
    try:
        notetype_id = ensure_cloze_notetype(col)
        note = _add(
            col,
            notetype_id,
            Text="It&#x27;s a {{c1::versatile}} ingredient.",
            Word="versatile",
            Hint="having many uses",
            Definition="[sound:versatile.mp3] having many different uses",
            Source='<span class="od-speaker">Jason Chan</span> · 6 Minute English',
        )
        card = note.cards()[0]
        assert card.question_av_tags() == []  # the front gives nothing away
        tts = [t for t in card.answer_av_tags() if isinstance(t, TTSTag)]
        assert len(tts) == 1
        assert tts[0].lang == "en_GB"
        assert tts[0].field_text == "It's a versatile ingredient."
        assert "Jason Chan" in card.answer()
        # creating it again returns the same note type
        assert ensure_cloze_notetype(col) == notetype_id
    finally:
        col.close()


def test_note_type_from_the_previous_version_is_upgraded(tmp_path):
    col = Collection(str(tmp_path / "c.anki2"))
    try:
        models = col.models
        notetype = models.new(CLOZE_NOTETYPE_NAME)
        notetype["type"] = MODEL_CLOZE
        for name in CLOZE_FIELDS:
            models.add_field(notetype, models.new_field(name))
        template = models.new_template("Cloze")
        template["qfmt"], template["afmt"] = CLOZE_FRONT, OLD_CLOZE_BACKS[0]
        models.add_template(notetype, template)
        notetype["css"] = CLOZE_CSS
        models.add(notetype)
        notetype_id = models.id_for_name(CLOZE_NOTETYPE_NAME)
        old = _add(
            col,
            notetype_id,
            Text='I {{c1::love}} it. <span class="od-speaker">— Becca</span>',
            Word="love",
            Source="<a>Real Easy English</a>",
        )

        assert upgrade_cloze_notetype(col) == 1
        old.load()
        assert old["Text"] == "I {{c1::love}} it."
        assert old["Source"] == (
            '<span class="od-speaker">Becca</span> · <a>Real Easy English</a>'
        )
        tts = [t for t in old.cards()[0].answer_av_tags() if isinstance(t, TTSTag)]
        assert [t.field_text for t in tts] == ["I love it."]
        # a second run changes nothing
        assert upgrade_cloze_notetype(col) == 0

        # a back template the user edited is left alone
        notetype = models.get(notetype_id)
        notetype["tmpls"][0]["afmt"] = OLD_CLOZE_BACKS[0] + "<p>mine</p>"
        models.update_dict(notetype)
        assert upgrade_cloze_notetype(col) == 0
        assert models.get(notetype_id)["tmpls"][0]["afmt"].endswith("<p>mine</p>")
    finally:
        col.close()
