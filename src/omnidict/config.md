## `definition`

Controls what information is fetched and rendered when a definition is added to a card.

**`include_audio`** — boolean, default: `false`  
Download pronunciation audio files and embed them in the card.

**`include_phonemic_transcriptions`** — boolean, default: `true`  
Show phonemic (IPA) transcriptions alongside each pronunciation.

**`include_translations`** — boolean, default: `true`  
Show the translation for each sense and its example sentences.

**`include_examples`** — boolean, default: `false`  
Show example sentences for each sense.

## `editor`

Controls which dictionary buttons appear in the Anki card editor toolbar.

### `buttons`

A list of dictionary identifiers. Each entry adds one button to the editor toolbar. The format is:

`{provider-id}.{dictionary-id}`

**Supported values**

- `cambridge-dictionary.english-chinese-traditional`: Cambridge English–Chinese (Traditional) Dictionary
- `cambridge-dictionary.english-chinese-simplified`: Cambridge English–Chinese (Simplified) Dictionary
- `cambridge-dictionary.english-advanced-learner`: Cambridge Advanced Learner's Dictionary & Thesaurus
- `cambridge-dictionary.english-academic-content`: Cambridge Academic Content Dictionary
- `cambridge-dictionary.english-business-english`: Cambridge Business English Dictionary

## `quick_add`

The **查+加** button in the editor (default shortcut `Ctrl+Shift+Return`): looks up the
word field, fills the definition field and, in the Add window, adds the note right away.

**`shortcut`** — string, default: `"Ctrl+Shift+Return"`  
**`word_field`** — string, default: `""` (the first field)  
**`definition_field`** — string, default: `""` (the second field)  
Field names are matched without regard to case. Also used as the defaults of the batch dialog.

**`dictionary`** — string, default: `""` (the first entry of `editor.buttons`)  
Same `{provider-id}.{dictionary-id}` format as `editor.buttons`.

**`follow_redirects`** — boolean, default: `true`  
Accept Cambridge's redirects (e.g. *clicked* → *click*, or another dictionary when the
word isn't in this one) without asking.

## `batch`

Tools → **OmniDict 批次加單字…**: paste one word per line, get one note per word.

**`delay_seconds`** — number, default: `1.5`  
Pause between words, so Cambridge isn't asked too fast.

**`menu_shortcut`** — string, default: `"Ctrl+Shift+B"` (empty to disable)
