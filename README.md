# Hebrew Audio Transcriber

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![PyQt5](https://img.shields.io/badge/PyQt5-GUI-orange)
![Speech to Text](https://img.shields.io/badge/speech--to--text-transcription-blueviolet)

A desktop application that transcribes Hebrew audio and video into timestamped, speaker-labelled text, using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (a CTranslate2 reimplementation of OpenAI's Whisper) with Hebrew-specialised models, behind a PyQt5 GUI. Everything runs locally: no audio ever leaves your machine, and no account is needed.

## Screenshots

|              | File Selection                                            | Model Picking                                           |
| ------------ | --------------------------------------------------------- | ------------------------------------------------------ |
| English      | ![File selection screen](docs/screenshot-file-select.png) | ![Model picking screen](docs/screenshot-model-picking.png) |
| Hebrew (RTL) | ![File selection screen in Hebrew](docs/screenshot-file-select-he.png) | ![Model picking screen in Hebrew](docs/screenshot-model-picking-he.png) |

## Flow Chart

![Architecture diagram](docs/architecture.jpg)

## Features

Point it at one or more audio/video files (or drop a whole folder), and it walks you through a 3-step wizard: pick the file(s), pick a model, and transcribe.

- **Hebrew-specialised models** - defaults to [ivrit.ai](https://www.ivrit.ai)'s Hebrew fine-tunes of Whisper, not stock Whisper (trained overwhelmingly on English); generic Whisper sizes remain available for mixed-language audio.
- **Timestamped, speaker-labelled turns** - each block shows its position in the audio and, where identifiable, who's speaking.
- **Batch transcription** - select several files or drop a folder, and get back one combined document from a single model load.
- **Bilingual interface (English / עברית)** - a full, mirrored right-to-left Hebrew layout, one click or `Ctrl+Shift+L` away.
- **Hardware-aware model recommendations** - based on your actual CPU/RAM/GPU and the total duration of everything selected.
- **Saves automatically** next to the source file(s) - see [Working with the transcript](#working-with-the-transcript).

## Installation

**Requirements:** Python 3.10+, pip, Windows (primary target platform).

```bash
git clone https://github.com/KoganTheDev/hebrew-audio-transcriber.git
cd hebrew-audio-transcriber

python -m venv .venv
.venv\Scripts\activate

python -m pip install --upgrade pip
pip install -e .
```

The `pip` upgrade is not optional on Windows. A new venv carries the pip
that shipped with your interpreter, and on Python 3.11.0 that is pip 22.3,
which aborts long installs with `OSError: [Errno 2] No such file or
directory: '...\pip-build-tracker-...'`. This project downloads ~120 MB of
wheels, so it hits that reliably.

`pip install -e .` installs the **dependencies only**. The app itself runs
from `src/` rather than from `site-packages`: its modules are `config`,
`core` and `gui`, names too generic to publish into a shared environment, so
`pyproject.toml` declares no packages. The launchers put `src/` on the path
for you.

### NVIDIA GPU acceleration (optional)

This app detects an NVIDIA GPU automatically and uses it for transcription -
no setting to flip. It also needs the cuBLAS/cuDNN runtime, which
faster-whisper's backend doesn't bundle on its own:

```bash
pip install -e ".[gpu]"
```

Without it, the GPU is still detected and selected, but the first
transcription falls back to CPU when it can't find `libcublas`/`libcudnn`.
No CUDA toolkit needed - just this pip extra.

## Usage

```bash
python src\main.py
```

Needs the dependencies installed and `.venv` active (see Installation above) -
or launch `run.ps1` / `run.bat` instead, which run it against the project's
`.venv` whatever your shell is pointing at. Neither launcher installs anything
on its own; if `.venv` doesn't exist yet, they fail immediately with setup
instructions rather than silently falling back to a system Python that lacks
the dependencies. Run `run.ps1 -Setup` (or `run.bat setup`) to have the
launcher create `.venv` and install everything into it for you.

**Workflow:**
1. **Select file(s)** - drag in audio/video files or a whole folder; your CPU/RAM/GPU and the total duration selected are shown alongside.
2. **Choose a model** - pick from the table below. The app pre-selects the highest-accuracy model that will still finish in reasonable time on your hardware.
3. **Transcribe** - watch live progress, then open the finished transcript straight from the app.

### Models

| Model | Description | RAM | First-use download |
|---|---|---|---|
| Tiny | Ultra-fast, lowest quality | 1 GB | 76 MB |
| Base | Good balance of speed and quality | 2 GB | 145 MB |
| Small | Better accuracy | 3 GB | 484 MB |
| Medium | High accuracy, general purpose | 5 GB | 1.5 GB |
| Large | Best general-purpose model, very slow | 8 GB | 3.1 GB |
| **Ivrit Turbo** | **Hebrew-tuned, fast and accurate (default)** | **3 GB** | **1.6 GB** |
| Ivrit Large | Hebrew-tuned, highest accuracy, slow | 8 GB | 3.1 GB |

The two Ivrit models are [ivrit.ai](https://www.ivrit.ai/en/2025/02/13/training-whisper/) fine-tunes of Whisper trained on hundreds of hours of transcribed Hebrew. For Hebrew audio they make considerably fewer mistakes than any of the generic sizes above them, and Ivrit Turbo's reduced decoder makes it faster than Medium despite being a larger model. The generic sizes are still the better choice for mixed-language or non-Hebrew recordings.

Actual processing time isn't fixed: it's estimated from a one-time benchmark run on your own hardware the first time the app launches, then scaled by model size, the file's real duration, and whether speaker identification is enabled.

## Working with the transcript

The output of a run is a single, self-contained HTML file - not a `.txt` -
so a Hebrew line's right-to-left direction can be *declared* rather than
guessed by whatever program opens it. Open it in any browser to read it, and
edit it right there: click into any turn to fix the text, rename and
recolour speakers from the sidebar, or search across every file with `/`.

One thing worth knowing before you start editing: **edits save instantly to
your browser's local storage, not back to the file on disk.** Press
**"Save a copy"** (or `Ctrl+S`) to download a fresh HTML file with your edits
baked in - that's the one to keep or send to someone else.

Speaker identification is on by default (set how many speakers on the model
screen), and a `hebrew_terms.txt` file next to the app corrects names and
jargon the model gets wrong - copy
[`hebrew_terms.example.txt`](hebrew_terms.example.txt) to get started.

See **[docs/USING_THE_TRANSCRIPT.md](docs/USING_THE_TRANSCRIPT.md)** for the
full guide: editing, speaker renaming, confidence shading, audio playback,
and exactly how speaker identification and term correction each work.

## Development

```bash
pip install -e ".[dev]"
pytest
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and
the two structural rules enforced by tests and `import-linter`, and
[docs/TESTING.md](docs/TESTING.md) for test levels, coverage policy, CI
checks, and the jsdom front-end suite.

## License

MIT. See [LICENSE](LICENSE).
