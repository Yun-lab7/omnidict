"""Batch add: paste a list of words, get one note per word.

Words are looked up one at a time (the Cambridge browser handles one page at a time
anyway), with a short pause between words so the site isn't hammered. Each note is
added as soon as its definition arrives, so stopping halfway keeps what was done.

Optionally an episode of BBC Learning English (e.g. 6 Minute English) can be read
first: its vocabulary list is added to the words, and each card gets the sentence
from the transcript where the word was used, plus the episode as its source.
"""

from anki.collection import Collection, SearchNode
from anki.decks import DeckId
from anki.models import NotetypeId
from aqt import mw
from aqt.operations import QueryOp
from aqt.operations.note import add_note
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QShortcut,
    QTimer,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import ask_user, show_warning, tooltip

from .bbc import Episode, EpisodeError, find_sentence, load_episode
from .quickadd import (
    batch_config,
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

# Remember the choices while Anki is open.
_last_choices: dict = {}
_dialog: "BatchAddDialog | None" = None

NONE_LABEL = "（不填）"
WORD_NOTETYPE_NAME = "OmniDict 單字"
WORD_NOTETYPE_FIELDS = ["Word", "Definition", "Sentence", "Source"]
_SENTENCE_FIELD_NAMES = ("sentence", "example", "context", "原句", "例句", "句子")
_SOURCE_FIELD_NAMES = ("source", "來源", "出處")
_WORD_NOTETYPE_CSS = """.card {
  font-family: arial, sans-serif;
  font-size: 20px;
  text-align: left;
  color: black;
  background-color: white;
}
.word { font-size: 32px; font-weight: bold; text-align: center; }
.sentence {
  margin-top: 1em;
  padding: 0.5em 0.8em;
  border-left: 4px solid #8ab4f8;
  font-style: italic;
}
.sentence b { font-style: normal; }
.od-speaker { font-style: normal; font-size: 0.8em; color: #777; white-space: nowrap; }
.source { margin-top: 0.8em; font-size: 0.75em; color: #777; }
.source a { color: inherit; }
.nightMode .card { color: #ddd; background-color: #2f2f31; }
"""


def fetch_page(url: str) -> tuple[str, str]:
    """Download a BBC or YouTube page, following redirects (runs in a background
    thread). Returns the final URL and the HTML."""
    import requests

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
                ),
                "Accept-Language": "en-GB,en;q=0.9",
            },
            # Skip YouTube's cookie-consent page in regions that show one.
            cookies={"CONSENT": "YES+", "SOCS": "CAI"},
        )
    except requests.RequestException as e:
        raise EpisodeError(f"連不上網站：{e}") from e
    if response.status_code != 200:
        raise EpisodeError(f"網站回應 {response.status_code}，讀不到這一頁")
    response.encoding = response.encoding or "utf-8"
    return response.url, response.text


def ensure_word_notetype(col: Collection) -> NotetypeId:
    """The "OmniDict 單字" note type (Word, Definition, Sentence, Source); created once."""
    existing = col.models.id_for_name(WORD_NOTETYPE_NAME)
    if existing:
        return NotetypeId(existing)
    models = col.models
    notetype = models.new(WORD_NOTETYPE_NAME)
    for name in WORD_NOTETYPE_FIELDS:
        models.add_field(notetype, models.new_field(name))
    template = models.new_template("Card 1")
    template["qfmt"] = '<div class="word">{{Word}}</div>'
    template["afmt"] = (
        '{{FrontSide}}\n<hr id="answer">\n{{Definition}}\n'
        '{{#Sentence}}<div class="sentence">{{Sentence}}</div>{{/Sentence}}\n'
        '{{#Source}}<div class="source">{{Source}}</div>{{/Source}}'
    )
    models.add_template(notetype, template)
    notetype["css"] = _WORD_NOTETYPE_CSS
    models.add(notetype)
    return NotetypeId(models.id_for_name(WORD_NOTETYPE_NAME))


def _guess_field(names: list[str], wanted: tuple[str, ...]) -> int | None:
    lowered = [n.casefold() for n in names]
    for candidate in wanted:
        if candidate in lowered:
            return lowered.index(candidate)
    return None


def is_duplicate(
    col: Collection, notetype_name: str, field_name: str, word: str
) -> bool:
    search = col.build_search_string(
        SearchNode(note=notetype_name),
        SearchNode(field=SearchNode.Field(field_name=field_name, text=word)),
    )
    return bool(col.find_notes(search))


class BatchAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        from .globals import config, provider_manager

        self.config = config
        self.provider_manager = provider_manager
        self.col = mw.col
        self.setWindowTitle("OmniDict 批次加單字")
        self.resize(600, 780)

        self.running = False
        self.stop_requested = False
        self.queue: list[str] = []
        self.position = 0
        self.failed: list[str] = []
        self.counts = {"added": 0, "skipped": 0, "failed": 0}
        self.episode: Episode | None = None
        self.episode_source = ""

        self._build_ui()
        self._load_choices()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        episode_row = QHBoxLayout()
        self.episode_edit = QLineEdit()
        self.episode_edit.setPlaceholderText(
            "（選填）BBC Learning English 或 YouTube 的節目網址，或 Ctrl+S 存下的網頁檔路徑"
        )
        self.episode_button = QPushButton("讀取節目")
        episode_row.addWidget(self.episode_edit, 1)
        episode_row.addWidget(self.episode_button)
        layout.addLayout(episode_row)
        self.episode_label = QLabel("")
        self.episode_label.setWordWrap(True)
        layout.addWidget(self.episode_label)

        layout.addWidget(QLabel("一行一個單字或片語（# 開頭的行會略過）："))
        self.words_edit = QPlainTextEdit()
        self.words_edit.setPlaceholderText("apple\nbreak the ice\nrecord")
        layout.addWidget(self.words_edit, 2)

        form = QFormLayout()
        self.deck_combo = QComboBox()
        self.notetype_combo = QComboBox()
        self.word_field_combo = QComboBox()
        self.definition_field_combo = QComboBox()
        self.sentence_field_combo = QComboBox()
        self.source_field_combo = QComboBox()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(
            "例如 6min::2026-11-05_Could_vaccines_cure_cancer（空格分隔多個標籤）"
        )
        self.notetype_button = QPushButton("建立單字筆記類型")
        self.notetype_button.setToolTip(
            f"建立「{WORD_NOTETYPE_NAME}」：Word、Definition、Sentence、Source 四個欄位"
        )
        self.dictionary_combo = QComboBox()
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 30.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setSuffix(" 秒")
        self.skip_duplicates_check = QCheckBox("略過已經有卡片的單字")
        self.follow_redirects_check = QCheckBox(
            "自動接受轉址（例如 clicked → click、改查其他字典）"
        )

        form.addRow("牌組", self.deck_combo)
        notetype_row = QHBoxLayout()
        notetype_row.addWidget(self.notetype_combo, 1)
        notetype_row.addWidget(self.notetype_button)
        form.addRow("筆記類型", notetype_row)
        form.addRow("單字欄位", self.word_field_combo)
        form.addRow("釋義欄位", self.definition_field_combo)
        form.addRow("原句欄位", self.sentence_field_combo)
        form.addRow("來源欄位", self.source_field_combo)
        form.addRow("標籤", self.tags_edit)
        form.addRow("字典", self.dictionary_combo)
        form.addRow("每個字間隔", self.delay_spin)
        form.addRow("", self.skip_duplicates_check)
        form.addRow("", self.follow_redirects_check)
        layout.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.status_label = QLabel("")
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("開始")
        self.start_button.setDefault(True)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.retry_button = QPushButton("把失敗的字放回清單")
        self.retry_button.setEnabled(False)
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.retry_button)
        buttons.addStretch()
        buttons.addWidget(close_box)
        layout.addLayout(buttons)

        qconnect(self.start_button.clicked, self.start)
        qconnect(self.stop_button.clicked, self.stop)
        qconnect(self.retry_button.clicked, self.put_failed_back)
        qconnect(close_box.rejected, self.reject)
        qconnect(self.notetype_combo.currentIndexChanged, self._fill_field_combos)
        qconnect(self.episode_button.clicked, self.read_episode)
        qconnect(self.episode_edit.returnPressed, self.read_episode)
        qconnect(self.notetype_button.clicked, self.create_word_notetype)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.start)

        self.inputs = [
            self.episode_edit,
            self.episode_button,
            self.notetype_button,
            self.sentence_field_combo,
            self.source_field_combo,
            self.tags_edit,
            self.words_edit,
            self.deck_combo,
            self.notetype_combo,
            self.word_field_combo,
            self.definition_field_combo,
            self.dictionary_combo,
            self.delay_spin,
            self.skip_duplicates_check,
            self.follow_redirects_check,
        ]

    def _load_choices(self) -> None:
        for deck in sorted(self.col.decks.all_names_and_ids(), key=lambda d: d.name):
            self.deck_combo.addItem(deck.name, deck.id)
        for notetype in self.col.models.all_names_and_ids():
            self.notetype_combo.addItem(notetype.name, notetype.id)
        for full_id, name in self.provider_manager.list_dictionaries():
            self.dictionary_combo.addItem(name, full_id)

        defaults = self.col.defaults_for_adding(current_review_card=None)
        self._select(self.deck_combo, _last_choices.get("deck_id", defaults.deck_id))
        self._select(
            self.notetype_combo,
            _last_choices.get("notetype_id", defaults.notetype_id),
        )
        self._select(
            self.dictionary_combo,
            _last_choices.get("dictionary", default_dictionary(self.config)),
        )
        self._fill_field_combos()
        self.tags_edit.setText(_last_choices.get("tags", ""))

        self.delay_spin.setValue(
            _last_choices.get("delay", batch_config(self.config)["delay_seconds"])
        )
        self.skip_duplicates_check.setChecked(
            _last_choices.get("skip_duplicates", True)
        )
        self.follow_redirects_check.setChecked(
            _last_choices.get(
                "follow_redirects", quick_add_config(self.config)["follow_redirects"]
            )
        )

    @staticmethod
    def _select(combo: QComboBox, data) -> None:
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _fill_field_combos(self, *_args) -> None:
        notetype_id = self.notetype_combo.currentData()
        notetype = self.col.models.get(NotetypeId(notetype_id)) if notetype_id else None
        names = [f["name"] for f in notetype["flds"]] if notetype else []
        for combo in (self.word_field_combo, self.definition_field_combo):
            combo.clear()
            combo.addItems(names)
        for combo in (self.sentence_field_combo, self.source_field_combo):
            combo.clear()
            combo.addItem(NONE_LABEL, None)
            for index, name in enumerate(names):
                combo.addItem(name, index)
        try:
            word_index, definition_index = find_field_indices(names, self.config)
        except ValueError:
            word_index, definition_index = 0, min(1, len(names) - 1)
        sentence_index = _guess_field(names, _SENTENCE_FIELD_NAMES)
        source_index = _guess_field(names, _SOURCE_FIELD_NAMES)
        remembered = _last_choices.get("fields", {}).get(notetype_id)
        if remembered:
            word_index, definition_index, sentence_index, source_index = remembered
        self.word_field_combo.setCurrentIndex(word_index)
        self.definition_field_combo.setCurrentIndex(definition_index)
        self._select(self.sentence_field_combo, sentence_index)
        self._select(self.source_field_combo, source_index)

    # ---------------------------------------------------------------- episode
    def read_episode(self) -> None:
        if self.running:
            return
        source = self.episode_edit.text().strip()
        if not source:
            show_warning("請先貼上節目網址。", parent=self)
            return
        self.episode_button.setEnabled(False)
        self.episode_label.setText("讀取節目中…")

        def on_success(episode: Episode) -> None:
            self.episode_button.setEnabled(True)
            previous_tag = self.episode.tag if self.episode else ""
            self.episode, self.episode_source = episode, source
            current = self.tags_edit.text().strip()
            if episode.tag and (not current or current == previous_tag):
                self.tags_edit.setText(episode.tag)
            existing = {
                w.casefold() for w in parse_word_list(self.words_edit.toPlainText())
            }
            new_words = [
                w for w, _ in episode.vocabulary if w.casefold() not in existing
            ]
            if new_words:
                text = self.words_edit.toPlainText().rstrip()
                self.words_edit.setPlainText(
                    "\n".join(([text] if text else []) + new_words)
                )
            self.episode_label.setText(
                f"已讀取：{episode.summary()}"
                + (f"，加入節目單字 {len(new_words)} 個" if new_words else "")
                + "。再補上你自己不會的字，按開始。"
            )

        def on_failure(e: Exception) -> None:
            self.episode_button.setEnabled(True)
            self.episode, self.episode_source = None, ""
            self.episode_label.setText("")
            show_warning(f"讀不到這一集：{e}", parent=self)

        QueryOp(
            parent=self,
            op=lambda _col: load_episode(source, fetch_page),
            success=on_success,
        ).failure(on_failure).run_in_background()

    def create_word_notetype(self) -> None:
        notetype_id = ensure_word_notetype(self.col)
        if self.notetype_combo.findData(notetype_id) < 0:
            self.notetype_combo.addItem(WORD_NOTETYPE_NAME, notetype_id)
        self._select(self.notetype_combo, notetype_id)
        self._fill_field_combos()
        tooltip(f"已建立並選好「{WORD_NOTETYPE_NAME}」", parent=self)

    def _set_running(self, running: bool) -> None:
        self.running = running
        for widget in self.inputs:
            widget.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.retry_button.setEnabled(not running and bool(self.failed))

    def _write(self, line: str) -> None:
        self.log.appendPlainText(line)

    # ---------------------------------------------------------------- run
    def start(self) -> None:
        if self.running:
            return
        words = parse_word_list(self.words_edit.toPlainText())
        if not words:
            show_warning("請先輸入至少一個單字。", parent=self)
            return
        word_index = self.word_field_combo.currentIndex()
        definition_index = self.definition_field_combo.currentIndex()
        sentence_index = self.sentence_field_combo.currentData()
        source_index = self.source_field_combo.currentData()
        chosen = [word_index, definition_index] + [
            i for i in (sentence_index, source_index) if i is not None
        ]
        if min(chosen) < 0 or len(set(chosen)) != len(chosen):
            show_warning("單字、釋義、原句、來源要選不同的欄位。", parent=self)
            return
        episode_text = self.episode_edit.text().strip()
        if episode_text and episode_text != self.episode_source:
            show_warning("節目網址改過了，請先按「讀取節目」。", parent=self)
            return
        if not episode_text:
            self.episode, self.episode_source = None, ""
        try:
            self.provider, self.dictionary_id = resolve_dictionary(
                self.provider_manager, self.dictionary_combo.currentData()
            )
        except ValueError as e:
            show_warning(str(e), parent=self)
            return

        self.deck_id = DeckId(self.deck_combo.currentData())
        self.notetype = self.col.models.get(
            NotetypeId(self.notetype_combo.currentData())
        )
        self.word_index, self.definition_index = word_index, definition_index
        self.sentence_index, self.source_index = sentence_index, source_index
        self.tags = self.tags_edit.text().split()
        self.word_field_name = self.notetype["flds"][word_index]["name"]
        self.options = definition_config(self.config)
        self.follow_redirects = self.follow_redirects_check.isChecked()
        self.skip_duplicates = self.skip_duplicates_check.isChecked()
        self.delay_ms = int(self.delay_spin.value() * 1000)

        _last_choices.update(
            deck_id=self.deck_combo.currentData(),
            notetype_id=self.notetype_combo.currentData(),
            dictionary=self.dictionary_combo.currentData(),
            delay=self.delay_spin.value(),
            skip_duplicates=self.skip_duplicates,
            follow_redirects=self.follow_redirects,
            tags=self.tags_edit.text(),
        )
        _last_choices.setdefault("fields", {})[self.notetype["id"]] = (
            word_index,
            definition_index,
            sentence_index,
            source_index,
        )

        self.queue, self.position, self.failed = words, 0, []
        self.counts = {"added": 0, "skipped": 0, "failed": 0}
        self.stop_requested = False
        self.log.clear()
        self.progress.setRange(0, len(words))
        self.progress.setValue(0)
        self._set_running(True)
        self._next()

    def stop(self) -> None:
        if self.running:
            self.stop_requested = True
            self.status_label.setText("查完目前這個字就停止…")

    def _next(self) -> None:
        if self.stop_requested or self.position >= len(self.queue):
            self._finish()
            return
        word = self.queue[self.position]
        self.status_label.setText(
            f"查詢「{word}」（{self.position + 1}/{len(self.queue)}）"
        )

        if self.skip_duplicates and is_duplicate(
            self.col, self.notetype["name"], self.word_field_name, word
        ):
            self._record(word, "skipped", f"略過　{word}（已經有卡片）")
            self._advance(wait=False)
            return

        QueryOp(
            parent=self,
            op=lambda col: fetch_definition_html(
                col,
                self.provider,
                self.dictionary_id,
                lookup_term(word),
                self.options,
                follow_redirects=self.follow_redirects,
            ),
            success=lambda result: self._add(word, result),
        ).failure(lambda e: self._fetch_failed(word, e)).run_in_background()

    def _add(self, word: str, result) -> None:
        note = self.col.new_note(self.notetype)
        note.fields[self.word_index] = word
        note.fields[self.definition_index] = result.html
        note.tags = list(self.tags)
        notes = []
        if result.redirected and result.word != word:
            notes.append(f"用「{result.word}」的釋義")
        if self.episode is not None:
            if self.sentence_index is not None:
                match = find_sentence(self.episode, word, (result.word,))
                if match:
                    note.fields[self.sentence_index] = match.html()
                else:
                    notes.append("逐字稿裡找不到原句")
            if self.source_index is not None:
                note.fields[self.source_index] = self.episode.source_html()
        extra = f"（{'；'.join(notes)}）" if notes else ""

        def on_added(_changes) -> None:
            self._record(word, "added", f"✓　{word}{extra}")
            self._advance()

        def on_failed(e: Exception) -> None:
            self._record(word, "failed", f"✗　{word}：加入卡片失敗（{e}）")
            self._advance()

        add_note(parent=self, note=note, target_deck_id=self.deck_id).success(
            on_added
        ).failure(on_failed).run_in_background()

    def _fetch_failed(self, word: str, error: Exception) -> None:
        self._record(word, "failed", f"✗　{describe_error(error, word)}")
        self._advance()

    def _record(self, word: str, kind: str, line: str) -> None:
        self.counts[kind] += 1
        if kind == "failed":
            self.failed.append(word)
        self._write(line)

    def _advance(self, wait: bool = True) -> None:
        self.position += 1
        self.progress.setValue(self.position)
        if self.position >= len(self.queue) or self.stop_requested:
            self._finish()
        elif wait and self.delay_ms:
            QTimer.singleShot(self.delay_ms, self._next)
        else:
            QTimer.singleShot(0, self._next)

    def _finish(self) -> None:
        if not self.running:
            return
        not_done = len(self.queue) - self.position
        summary = (
            f"完成：新增 {self.counts['added']}、略過 {self.counts['skipped']}、"
            f"失敗 {self.counts['failed']}"
        )
        if not_done:
            summary += f"、未處理 {not_done}（已停止）"
            self.failed.extend(self.queue[self.position :])
        self.status_label.setText(summary)
        self._write("—— " + summary)
        self._set_running(False)
        tooltip(summary, parent=mw)

    def put_failed_back(self) -> None:
        self.words_edit.setPlainText("\n".join(self.failed))
        self.failed = []
        self.retry_button.setEnabled(False)

    # ---------------------------------------------------------------- close
    def reject(self) -> None:
        # Close button, window X and Esc all end here. The dialog is only hidden,
        # so the log is still there when it is reopened.
        if self.running:
            if not ask_user("還在加卡，確定要停止並關閉嗎？", parent=self):
                return
            self.stop_requested = True
        super().reject()


def open_batch_dialog() -> None:
    global _dialog
    if mw.col is None:
        return
    if _dialog is None or _dialog.col is not mw.col:
        _dialog = BatchAddDialog(mw)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()


def add_menu_item() -> None:
    from aqt.qt import QAction

    from .globals import config

    action = QAction("OmniDict 批次加單字…", mw)
    keys = batch_config(config)["menu_shortcut"]
    if keys:
        action.setShortcut(QKeySequence(keys))
    qconnect(action.triggered, open_batch_dialog)
    mw.form.menuTools.addAction(action)
