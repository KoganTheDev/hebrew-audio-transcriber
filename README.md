# Hebrew Audio Transcriber

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![PyQt5](https://img.shields.io/badge/PyQt5-GUI-orange)
![Speech to Text](https://img.shields.io/badge/speech--to--text-transcription-blueviolet)

A desktop application that transcribes Hebrew audio and video into timestamped, speaker-labelled text, using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (a CTranslate2 reimplementation of OpenAI's Whisper) with Hebrew-specialised models, behind a PyQt5 GUI. Everything runs locally: no audio ever leaves your machine, and no account is needed.

## Overview

Point it at one or more audio/video files (or drop a whole folder), and it walks you through a 3-step wizard: pick the file(s), pick a model, and transcribe.
- **Hebrew-specialised models**: defaults to [ivrit.ai](https://www.ivrit.ai)'s Hebrew fine-tunes of Whisper rather than stock Whisper, which is trained overwhelmingly on English. The generic Whisper sizes remain available for mixed-language audio.
- **Timestamped speaker turns**: each block of the transcript carries its position in the audio and, where speakers can be identified, who is talking.
- **Batch transcription**: select several files, or drop a folder, and get back one combined document - each source file gets its own titled section, transcribed in a single model load instead of one run per file.
- **Bilingual interface (English / עברית)**: starts in English; the עב/EN button in the header switches the whole UI to a fully mirrored right-to-left Hebrew layout, and the choice is remembered between runs.
- **Real hardware-aware recommendations**: the suggested model is computed from your actual CPU/RAM and the total duration of everything you've selected.
- **Output saving location:** The output is saved automatically next to the audio - beside the file itself for a single run, or beside the first file for a batch (see "Output format" below).

### Output format

The transcript is a single, self-contained HTML file - not a `.txt` file. That's a deliberate choice, not a cosmetic one: a plain-text file carries no direction metadata, so a Hebrew line's alignment is *guessed* by whatever program opens it (most text viewers and editors hardcode left-to-right), and there is no plain-text mechanism that reliably fixes this. HTML lets direction be *declared* (`dir="rtl"`) instead of guessed, which is the only approach that renders correctly everywhere. The file is fully offline - no external fonts, no CDN, nothing loaded over the network - consistent with the rest of the app.

Each source file becomes its own titled section (a table of contents links between them when there's more than one), and within a section each speaker turn is its own block: a header line with the timestamp and speaker, then the speech below it, one sentence per line for easy scanning.

```html
<header class="file-bar" data-file-accent="0"><h1>meeting.m4a</h1><span class="file-position">1 / 1</span></header>
<article class="turn" data-turn="0-0" data-start="0.00" data-end="4.00" data-speaker="0" data-palette="0">
  <h2><button class="ts" dir="ltr" data-start="0.00" data-end="4.00">⁦0:00 - 0:04⁩</button>
      <button class="spk" data-speaker="0" data-palette="0">דובר 1</button></h2>
  <div class="body" contenteditable="true"><p>שלום, מה שלומך היום?</p></div>
</article>
```

A timestamp is a *range*, not an instant: clicking it seeks to the start and plays exactly to the end, then stops - so it names the section you're about to hear, not just where it begins. Ranges are wrapped in Unicode directional isolates (`dir="ltr"` controls the browser's layout; the isolates keep plain-text copies ordered correctly too, "start - end" rather than reversed). The hyphen between the two times is a neutral character sitting between two LTR digit runs inside RTL text - without the isolate it can reorder the same way mirrored brackets used to. If you process the copied text with your own tools, strip `U+2066`, `U+2069` and `U+200F` before parsing.

### Correcting the transcript

The transcript is not just something to read - it is where the proofreading happens. Open it in a browser and:

- **Edit any turn** by clicking into it and typing. No edit mode, no save button.
- **Name, recolour and reassign speakers.** Type a real name once in the speakers strip and every "דובר 1" in that recording becomes it. Names stay per file by default, since speaker 1 in one recording is rarely the same person as speaker 1 in another; one button copies them across when it really is the same meeting. If diarization missed someone or merged two people, "+ הוספת דובר" adds a speaker with its own colour from a verified eight-colour palette, and clicking any turn's speaker label opens a menu to move that turn to a different speaker.
- **See what the model doubted.** Whisper records a confidence for every word, and the toolbar toggle shades the ones that fell below the same threshold the Hebrew term-correction pass uses. This is the difference between re-reading a whole transcript and looking at the twenty words that need it. Editing a turn clears its shading, because the confidence no longer describes what is now there.
- **Listen exactly to a turn.** The transcript is written next to its audio, so clicking a timestamp seeks, plays, and pauses again at the turn's end - and the turn being spoken is highlighted while it plays. If the audio is moved away or is in a container the browser can't play, that recording's timestamps quietly become plain labels - the rest of the batch is unaffected.
- **Search** across every file with `/`, stepping through matches with Enter. Matching ignores nikud and treats final letter forms as the same letter.
- **Copy it out.** Every section has an always-visible plain-text panel with checkboxes for timestamps and speaker names, kept in sync with your edits, plus a per-turn copy button. Every copy - a turn or the whole panel - confirms itself with a brief toast.
- **Keep your place in a batch.** Each file's name stays pinned below the toolbar as you scroll through it, in its own accent colour, so it's hard to drift from one recording's turns into the next one's without noticing.

#### Where your edits actually live

**This is worth understanding, because it is not what you would assume.** A page opened from a `file://` path cannot write back to its own file - browsers block that outright, and the API that would allow it is unavailable to documents loaded from disk. So:

- Every keystroke saves **instantly to your browser's local storage**, keyed to that transcript. Close the tab, reopen the file, and your work is there. The status reads **"נשמר בדפדפן" / "Saved in browser"** to say exactly that.
- The `.html` file on disk is **not** updated. To get a file containing your edits, press **"Save a copy"** (or `Ctrl+S`), which downloads a fresh, fully self-contained HTML with everything baked in. That copy is itself a working editor.

The practical consequence: edits live in the browser you made them in. Emailing the original `.html` to someone, or opening it on another machine, will not carry them - export a copy first. Re-running transcription on the same audio also produces a new document with a new identity, so its predecessor's saved edits no longer apply to it.

If a file in a batch fails to transcribe, its section says so and every other file's transcript is still produced - one bad recording doesn't cost you the rest of the batch.

### Speaker identification

Enabled by default, with a speaker count you can set on the model screen. Telling it exactly how many people are in the recording matters: fixing the count is considerably more reliable than letting the app infer it.

Two paths, chosen automatically:

- **One speaker per channel** (some phone and VoIP call recorders): each channel is transcribed separately, so attribution is exact. Detection is strict, since most stereo audio is really a duplicated mono mix. This roughly doubles transcription time.
- **Single microphone**: neural diarization via [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), running offline with no account required. Model weights (~36 MB) download once on first use. Adds roughly a third of the audio's duration to processing time.

If speaker identification fails for any reason, the transcript is still saved — just without labels.

### Correcting names and jargon

Words the model reliably mangles — people, places, organisations, professional vocabulary — can be listed in a `hebrew_terms.txt` file next to where you run the app. Copy [`hebrew_terms.example.txt`](hebrew_terms.example.txt) to get started. Without that file, nothing happens.

Only words the model itself flagged as uncertain are considered, and only your listed terms are candidates. Matching is aware of how Hebrew is actually misheard (א/ע, כ/ק, ט/ת) and of prefixes, so listing `ירושלים` also covers `בירושלים`. Every substitution is written to `speech_to_text.log` so you can check it.

This is not a spell checker, and adding ordinary vocabulary makes it worse rather than better — see the comments in the example file for why.


## Screenshots

|              | File Selection                                            | Model Picking                                           |
| ------------ | --------------------------------------------------------- | ------------------------------------------------------ |
| English      | ![File selection screen](docs/screenshot-file-select.png) | ![Model picking screen](docs/screenshot-model-picking.png) |
| Hebrew (RTL) | ![File selection screen in Hebrew](docs/screenshot-file-select-he.png) | ![Model picking screen in Hebrew](docs/screenshot-model-picking-he.png) |

## Flow Chart

![Architecture diagram](docs/architecture.jpg)

## Installation

**Requirements:** Python 3.9+, pip, Windows (primary target platform).

```bash
git clone https://github.com/KoganTheDev/hebrew-audio-transcriber.git
cd hebrew-audio-transcriber

python -m venv .venv
.venv\Scripts\activate

pip install -e .
```

For development (tests, linting):

```bash
pip install -r requirements-dev.txt
```

## Usage

```bash
python -m speech_to_text.main
```


**Workflow:**
1. **Select Audio File(s)**: drag one or more files into the drop zone (or click to browse, or drop a whole folder). Your CPU/RAM/GPU are shown alongside the total duration of everything selected; each file can be removed individually before continuing.
2. **Choose Model**: pick from the models below, and set whether to identify speakers. The app pre-selects the highest-accuracy model that will still finish within a reasonable time on your hardware, based on the total duration of the batch.
3. **Transcribe**: watch live progress - including which file of the batch is currently running - or cancel and return to model selection at any point. Progress and status messages follow the selected UI language, even if you switch mid-run. On completion, the combined transcript is saved next to the source file(s), with an **Open transcript** button that launches it in your browser.

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

Actual processing time isn't fixed: it's estimated from a one-time benchmark run on your own CPU the first time the app launches, then scaled by model size, the file's real duration, and whether speaker identification is enabled.

## Project Structure

```
speech_to_text/
├── main.py                    # Entry point: logging setup, dependency checks, launches the GUI
├── config.py                  # Model definitions and app-wide constants
├── hardware_detection.py      # CPU/RAM/GPU probing, model recommendation, time estimation
├── core/
│   ├── transcriber.py         # Wraps faster_whisper.WhisperModel
│   ├── segments.py            # Structured transcript: timings, per-word confidence, speaker
│   ├── formatting.py          # Turn merging and self-contained RTL HTML rendering
│   ├── assets/                # transcript.css / transcript.js, inlined into the output
│   ├── options.py             # Settings for one run, passed to the worker process
│   ├── audio_source.py        # PyAV decoding and one-speaker-per-channel detection
│   ├── diarization.py         # sherpa-onnx speaker identification and span assignment
│   ├── hebrew_correct.py      # Confidence-gated correction against a user term list
│   ├── hebrew_text.py         # Shared Hebrew normalization (nikud, final forms, clitics)
│   ├── worker.py              # Runs transcription in a separate OS process
│   ├── calibration.py         # One-time hardware benchmark (also runs out-of-process)
│   └── dependencies.py        # Installs missing runtime dependencies on first launch
└── gui/
    ├── main_window.py         # Main window, wizard navigation, transcription lifecycle
    ├── i18n.py                # English/Hebrew string table, language state, persistence
    ├── widgets.py             # IconTextButton: direction-independent icon+text nav button
    ├── threads.py             # QThread bridge between the GUI and the background process
    ├── steps/                 # One module per wizard step (file select / model select / transcribe)
    ├── theme.py               # Colors, fonts, QSS stylesheet builders
    ├── icons.py               # Tabler icon SVGs, rendered to QPixmap
    └── audio_utils.py         # Real audio/video duration probing (via PyAV)

tests/                          # pytest suite covering config, hardware detection, transcriber, and integration
docs/
├── architecture.drawio         # Editable source for the architecture diagram
└── architecture.jpg            # Rendered diagram (embedded above)
```

## Testing

```bash
pytest                                    # full suite
pytest --cov=speech_to_text --cov-report=html   # with coverage report
pytest tests/test_transcriber.py -v       # a single module
```

**One gap worth knowing about:** the transcript document's JavaScript - editing, autosave, speaker
renaming, search, audio, export - has no automated coverage. There is no JS test runner here, and
adding one would be a bigger change than the feature it tests. The Python suite covers what Python
can honestly assert about generated HTML (markup shape, data payload, escaping, the offline
guarantee, and WCAG colour contrast in both schemes). Everything else is a written checklist:
[`docs/transcript-manual-checks.md`](docs/transcript-manual-checks.md). Work it before shipping a
change to `core/assets/`.

### Comparing models on your own audio

`tests/eval/` holds a dev-only harness, kept out of the pytest suite because it needs real recordings and takes minutes:

```bash
python -m tests.eval.compare_models path/to/audio.m4a --models medium ivrit-turbo
```

It writes both transcripts side by side for reading, plus speed and confidence metrics.

Note what those metrics are and are not. Without a reference transcript there is no accuracy percentage to report: confidence figures correlate with quality but do not measure it, and a confidently wrong model scores well. Hand-correct a few minutes of transcript and pass it with `--reference` to get a real word error rate, computed with Hebrew-appropriate normalization (nikud, final letters, and the app's own timestamps and speaker labels are all discounted).

## License

MIT. See [LICENSE](LICENSE).
