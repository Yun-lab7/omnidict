# OmniDict

[![Latest release](https://badgen.net/github/release/danny900714/omnidict)](https://github.com/danny900714/omnidict/releases/latest)
[![CI/CD](https://github.com/danny900714/omnidict/actions/workflows/cicd.yaml/badge.svg)](https://github.com/danny900714/omnidict/actions/workflows/cicd.yaml)
[![Anki version](https://badgen.net/static/Anki/25.07-26.08.1+?icon=Anki)](https://github.com/ankitects/anki/releases)
[![License](https://badgen.net/github/license/danny900714/omnidict?color=purple)](https://github.com/danny900714/omnidict/blob/main/LICENSE)

**Omnidict is the only Anki dictionary add-on you'll ever need.**

> [!NOTE]
> **About this fork.** This is a modified version of
> [danny900714/omnidict](https://github.com/danny900714/omnidict), licensed under the
> same AGPL-3.0. Changes (2026-11-05):
>
> - Inside Anki, Cambridge Dictionary pages and audio are loaded in a real browser
>   (Anki's built-in Qt WebEngine) instead of `requests`. On some networks Cloudflare
>   answers `requests` with `403 Forbidden`; a browser passes its check normally. If
>   Cloudflare asks to confirm you are a person, a window opens and you answer it
>   yourself. The add-on does not fake a browser or solve the check for you.
> - Outside Anki (tests, scripts), the original `requests` session is still used.
>
> See `src/omnidict/provider/fetcher.py` and `src/omnidict/provider/browser.py`.
>
> Changes (2026-11-07), for adding cards faster:
>
> - **查+加** editor button (`Ctrl+Shift+Return`): looks up the word field, fills the
>   definition field and, in the Add window, adds the note right away.
> - **Tools → OmniDict 批次加單字…** (`Ctrl+Shift+B`): paste one word per line and get
>   one note per word, with a pause between lookups, duplicate skipping and a report.
> - New `quick_add` and `batch` sections in the config (see `config.md`).
>
> See `src/omnidict/quickadd.py` and `src/omnidict/batch.py`.

It seamlessly integrates multiple dictionaries, letting you create definition cards effortlessly.
The definition field is fully customizable — choose whether to include *pronunciation audio*,
*phonemic transcriptions*, *translations* and *examples*.
Cards created by this add-on work on all platforms.

![Review card on Anki](images/review.png)

## Features

- Add definitions, translations, pronunciation audio, phonemic transcriptions, and examples to your cards (fully customizable).
- Multiple dialect support (e.g., British and American English).
- Dark mode support.
- Cards work on Anki, AnkiDroid, Anki Mobile, and AnkiWeb.
- Dictionary support
  - Cambridge Dictionary
    - Cambridge English–Chinese (Simplified) Dictionary
    - Cambridge English-Chinese (Traditional) Dictionary
    - Cambridge Advanced Learner's Dictionary & Thesaurus
    - Cambridge Academic Content Dictionary
    - Cambridge Business English Dictionary
  - more to come, contributions welcomed!

## Installation

### AnkiWeb

The easiest way to install OmniDict is through [AnkiWeb](https://ankiweb.net/shared/info/702300994).

### Manual installation

1. Download the latest `.ankiaddon` file from the [release tab](https://github.com/danny900714/omnidict/releases/latest)
(you might need to click on Assets below the description to reveal the download links)
2. Open the folder where your downloads are located and double-click on the downloaded .ankiaddon file.
3. Follow the installation prompt and restart Anki if it asks you to

## Contributing

Contributions are always welcome!

See [CONTRIUBTING.md](./CONTRIBUTING.md) for ways to get started.

