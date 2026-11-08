from typing import LiteralString

from anki.collection import Collection
from aqt import gui_hooks
from aqt.editor import Editor
from aqt.operations import QueryOp
from aqt.utils import ask_user, shortcut, show_critical, show_info, show_warning
from aqt.webview import WebContent

from .provider import (
    DefinitionNotFoundError,
    DefinitionParseError,
    DefinitionRedirectedError,
    Provider,
)


def add_editor_stylesheet(web_content: WebContent, context: object | None):
    from .globals import addon_package

    if isinstance(context, Editor):
        web_content.css.append(f"/_addons/{addon_package}/web/editor.css")


def make_dictionary_button_clicked_handler(
    provider: Provider, dictionary_id: str, definition_config: dict[str, bool]
):
    # Function call stack:
    # handle_fetch_definition_button_clicked -> after_save -> fetch_definition -> fetch_definition_op -> set_definition
    #                                                                                                 \
    #                                                                                                  -> handle_fetch_definition_error (if error occurs)
    from .globals import _

    def handle_fetch_definition_button_clicked(editor: Editor):
        def after_save():
            current_field = editor.currentField
            if current_field is None or editor.note is None:
                return
            if current_field == 0:
                show_info(_("Click the next field to fetch definition."))
                return

            word = editor.note.fields[current_field - 1]
            if not word:
                show_warning(_("Please enter a word in the field above to proceed."))
                return

            ########################### Callbacks Start ###########################
            def set_definition(html: str) -> None:
                if editor.note is not None:
                    editor.note.fields[current_field] = html
                editor.loadNoteKeepingFocus()

            def handle_fetch_definition_error(
                e: Exception, dictionary_id: str, word: str
            ) -> None:
                if isinstance(e, DefinitionNotFoundError):
                    show_critical(
                        _('No definition found for "{word}"').format(word=word),
                        parent=editor.parentWindow,
                    )
                elif isinstance(e, DefinitionRedirectedError):
                    redirected_word = e.redirected_word
                    redirected_dictionary_id = e.redirected_dictionary_id

                    if (
                        redirected_dictionary_id is not None
                        and redirected_dictionary_id != dictionary_id
                    ):
                        dictionary_info = provider.get_dictionary_info(dictionary_id)
                        redirected_dictionary_info = provider.get_dictionary_info(
                            redirected_dictionary_id
                        )

                        ask_user(
                            _(
                                '"{word}" wasn\'t found in "{dictionary_name}". Would you like to search in "{redirected_dictionary_name}" instead?',
                            ).format(
                                word=word,
                                dictionary_name=dictionary_info.name
                                if dictionary_info is not None
                                else dictionary_id,
                                redirected_dictionary_name=redirected_dictionary_info.name
                                if redirected_dictionary_info is not None
                                else redirected_dictionary_id,
                            ),
                            callback=lambda ok: (
                                fetch_definition(
                                    redirected_dictionary_id, redirected_word
                                )
                                if ok
                                else None
                            ),
                            parent=editor.parentWindow,
                        )
                    else:
                        ask_user(
                            _(
                                '"{word}" wasn\'t found. Would you like to use the definition for "{redirected_word}" instead?'
                            ).format(word=word, redirected_word=redirected_word),
                            callback=lambda ok: (
                                fetch_definition(dictionary_id, redirected_word)
                                if ok
                                else None
                            ),
                            parent=editor.parentWindow,
                        )
                elif isinstance(e, DefinitionParseError):
                    show_critical(
                        _(
                            'Failed to parse the definition for "{word}". Please report this issue to the developer.\n{error}'
                        ).format(word=word, error=e),
                        parent=editor.parentWindow,
                    )
                else:
                    show_critical(
                        _("An unexpected error occurred:\n{error}").format(error=e),
                        parent=editor.parentWindow,
                    )

            def fetch_definition_op(
                col: Collection, dictionary_id: str, word: str
            ) -> str:
                definition = provider.fetch_definition(
                    dictionary_id,
                    word,
                    download_audio=definition_config["include_audio"],
                )
                if definition_config["include_audio"]:
                    definition.save_audio_files(col)
                return definition.render_html(**definition_config)

            def fetch_definition(dictionary_id: str, word: str) -> None:
                op = QueryOp(
                    parent=editor.parentWindow,
                    op=lambda col: fetch_definition_op(col, dictionary_id, word),
                    success=set_definition,
                )
                op.failure(
                    lambda e: handle_fetch_definition_error(e, dictionary_id, word)
                ).with_progress().run_in_background()

            ########################### Callbacks End ###########################

            if editor.note.fields[current_field]:
                ask_user(
                    _(
                        "Will overwrite existing content in the current field. Do you want to proceed?"
                    ),
                    lambda ok: fetch_definition(dictionary_id, word) if ok else None,
                )
                return

            fetch_definition(dictionary_id, word)

        editor.call_after_note_saved(after_save)

    return handle_fetch_definition_button_clicked


def add_editor_buttons(buttons: list[str], editor: Editor) -> None:
    from .globals import config, provider_manager

    if (
        config is not None
        and "editor" in config
        and "buttons" in config["editor"]
        and isinstance(config["editor"]["buttons"], list)
    ):
        for provider_dictionary_id in config["editor"]["buttons"]:
            split_ids: list[LiteralString] = provider_dictionary_id.split(".")
            if len(split_ids) != 2:
                print(
                    f"Invalid provider dictionary id in config.editor.buttons: {provider_dictionary_id}"
                )
                continue

            # Get provider
            provider_id, dictionary_id = split_ids
            provider = provider_manager.get_provider(provider_id)
            if provider is None:
                print(f"Provider not found: {provider_id}")
                continue

            # Get dictionary
            dictionary_info = provider.get_dictionary_info(dictionary_id)
            if dictionary_info is None:
                print(f"{provider.name()} doesn't support dictionary: {dictionary_id}")
                continue

            # Get definition config
            definition_config = {}
            if (
                config is not None
                and "definition" in config
                and isinstance(config["definition"], dict)
            ):
                definition_config: dict = config["definition"]
                definition_config.setdefault("include_audio", False)
                definition_config.setdefault("include_phonemic_transcriptions", True)
                definition_config.setdefault("include_translations", True)
                definition_config.setdefault("include_examples", False)

            icon = (
                dictionary_info.icon
                if dictionary_info.icon is not None
                else provider.icon()
            )
            keys = "Ctrl+Shift+D"
            button = editor.addButton(
                icon=icon,
                cmd=provider_dictionary_id,
                func=make_dictionary_button_clicked_handler(
                    provider, dictionary_id, definition_config
                ),
                id=provider_dictionary_id,
                label="" if icon else dictionary_info.name,
                tip=f"{dictionary_info.name} ({shortcut(keys)})",
                keys=keys,
            )
            buttons.append(button)

    add_quick_add_button(buttons, editor)


def handle_quick_add(editor: Editor) -> None:
    """Look up the word field, fill the definition field and (in Add) add the note.

    One shortcut instead of: click the next field, Ctrl+Shift+D, wait, Ctrl+Enter.
    """
    from anki.notes import NoteFieldsCheckResult
    from aqt.editor import EditorMode
    from aqt.utils import tooltip

    from .globals import _, config, provider_manager
    from .quickadd import (
        clean_word,
        default_dictionary,
        definition_config,
        describe_error,
        fetch_definition_html,
        find_field_indices,
        quick_add_config,
        resolve_dictionary,
    )

    def after_save() -> None:
        note = editor.note
        if note is None:
            return
        parent = editor.parentWindow
        field_names = [field["name"] for field in note.note_type()["flds"]]
        try:
            word_index, definition_index = find_field_indices(field_names, config)
            provider, dictionary_id = resolve_dictionary(
                provider_manager, default_dictionary(config)
            )
        except ValueError as e:
            show_warning(str(e), parent=parent)
            return

        word = clean_word(note.fields[word_index])
        if not word:
            show_warning(
                f"請先在「{field_names[word_index]}」欄位輸入單字。", parent=parent
            )
            editor.web.setFocus()
            return

        adding = editor.editorMode == EditorMode.ADD_CARDS and hasattr(
            parent, "_add_current_note"
        )

        def add_now() -> None:
            # The webview may still show the old fields; the note object is the truth.
            editor.loadNoteKeepingFocus()
            parent._add_current_note()  # same as Ctrl+Enter, without re-reading the webview

        def on_success(result) -> None:
            if editor.note is not note:
                return  # the user switched note type or closed the window meanwhile
            note.fields[definition_index] = result.html
            if result.redirected and result.word != word:
                tooltip(f"「{word}」用的是「{result.word}」的釋義", parent=parent)
            if adding:
                add_now()
            else:
                editor.loadNoteKeepingFocus()

        def on_failure(e: Exception) -> None:
            show_critical(describe_error(e, word), parent=parent)

        def start_fetch() -> None:
            options = definition_config(config)
            follow = quick_add_config(config)["follow_redirects"]
            QueryOp(
                parent=parent,
                op=lambda col: fetch_definition_html(
                    col, provider, dictionary_id, word, options, follow_redirects=follow
                ),
                success=on_success,
            ).failure(on_failure).with_progress(f"查詢「{word}」…").run_in_background()

        def maybe_fetch() -> None:
            if note.fields[definition_index].strip():
                if adding:
                    add_now()  # already has a definition: just add it
                    return
                ask_user(
                    _("Will overwrite existing content in the current field. Do you want to proceed?"),
                    lambda ok: start_fetch() if ok else None,
                    parent=parent,
                )
                return
            start_fetch()

        if adding and note.fields_check() == NoteFieldsCheckResult.DUPLICATE:
            ask_user(
                f"已經有「{word}」的卡片了，還要再加一張嗎？",
                lambda ok: maybe_fetch() if ok else None,
                parent=parent,
            )
            return
        maybe_fetch()

    editor.call_after_note_saved(after_save)


def add_quick_add_button(buttons: list[str], editor: Editor) -> None:
    from .globals import config
    from .quickadd import quick_add_config

    keys = quick_add_config(config)["shortcut"]
    buttons.append(
        editor.addButton(
            icon=None,
            cmd="omnidict-quick-add",
            func=handle_quick_add,
            id="omnidict-quick-add",
            label="查+加",
            tip=f"查單字並加入卡片 ({shortcut(keys)})",
            keys=keys,
        )
    )


gui_hooks.webview_will_set_content.append(add_editor_stylesheet)
gui_hooks.editor_did_init_buttons.append(add_editor_buttons)
