# Using the transcript

The output of a run is a single, self-contained HTML file, and it's not just
something to read - it's where the proofreading happens. This page covers
everything about that file: how it's built, how to edit it, and where those
edits actually go.

## Why HTML, not `.txt`

A plain-text file carries no direction metadata, so a Hebrew line's alignment
is *guessed* by whatever program opens it (most text viewers and editors
hardcode left-to-right), and there is no plain-text mechanism that reliably
fixes this. HTML lets direction be *declared* (`dir="rtl"`) instead of
guessed, which is the only approach that renders correctly everywhere. The
file is fully offline - no external fonts, no CDN, nothing loaded over the
network - consistent with the rest of the app.

Each source file becomes its own titled section, and within a section each
speaker turn is its own block: a header line with the timestamp and speaker,
then the speech below it, one sentence per line for easy scanning. A sidebar
lists every file and tracks which one you're currently scrolled into - it's
also where speaker names, colours and roster live, one panel per file, rather
than repeating that strip inside every section.

```html
<header class="file-bar" data-file-accent="0"><h1>meeting.m4a</h1><span class="file-position">1 / 1</span></header>
<article class="turn" data-turn="0-0" data-start="0.00" data-end="4.00" data-speaker="0" data-palette="0">
  <h2><button class="ts" dir="ltr" data-start="0.00" data-end="4.00">⁦0:00 - 0:04⁩</button>
      <button class="spk" data-speaker="0" data-palette="0">דובר 1</button></h2>
  <div class="body" contenteditable="true"><p>שלום, מה שלומך היום?</p></div>
</article>
```

A timestamp is a *range*, not an instant: clicking it seeks to the start and
plays exactly to the end, then stops - so it names the section you're about to
hear, not just where it begins. Ranges are wrapped in Unicode directional
isolates (`dir="ltr"` controls the browser's layout; the isolates keep
plain-text copies ordered correctly too, "start - end" rather than reversed).
The hyphen between the two times is a neutral character sitting between two
LTR digit runs inside RTL text - without the isolate it can reorder the same
way mirrored brackets used to. If you process the copied text with your own
tools, strip `U+2066`, `U+2069` and `U+200F` before parsing.

## Correcting the transcript

Open it in a browser and:

- **Edit any turn** by clicking into it and typing. No edit mode, no save button.
- **Name, recolour and reassign speakers from the sidebar.** Type a real name once and every "דובר 1" in that recording becomes it. Names stay per file by default, since speaker 1 in one recording is rarely the same person as speaker 1 in another; one button copies them across when it really is the same meeting. If diarization missed someone or merged two people, "+ הוספת דובר" adds a speaker with its own colour from a verified eight-colour palette, and clicking any turn's speaker label opens a menu to move that turn to a different speaker.
- **See what the model doubted.** Whisper records a confidence for every word, and the toolbar toggle shades the ones that fell below the same threshold the Hebrew term-correction pass uses. This is the difference between re-reading a whole transcript and looking at the twenty words that need it. Editing a turn clears its shading, because the confidence no longer describes what is now there.
- **Listen exactly to a turn.** The transcript is written next to its audio, so clicking a timestamp seeks, plays, and pauses again at the turn's end - and the turn being spoken is highlighted while it plays. The player has its own seek bar and a "current / total" readout; dragging the seek bar past a turn's end plays on rather than snapping back, the same way pressing play/pause already overrides a turn's bounds. If the audio is moved away or is in a container the browser can't play, that recording's timestamps quietly become plain labels - the rest of the batch is unaffected.
- **Search** across every file with `/`, stepping through matches with Enter. Matching ignores nikud and treats final letter forms as the same letter.
- **Copy it out, and edit from either side.** Every section has an always-visible plain-text panel with checkboxes for timestamps and speaker names, plus a per-turn copy button. It is not read-only: each row is itself editable and tied to its card, so a fix typed into the plain-text panel updates the card above it, and vice versa - there is nothing to keep in sync by hand. Every copy - a turn or the whole panel - confirms itself with a brief toast.
- **Keep your place in a batch.** Each file's name stays pinned below the toolbar as you scroll through it, in its own accent colour, and the sidebar's file list and speaker panel track the same thing, so it's hard to drift from one recording's turns into the next one's without noticing.
- **Light or dark, following your system.** The document defaults to your OS colour scheme, with its own toggle to override that. The palette is based on Catppuccin (Latte for light, Mocha for dark) - the same basis as the AnuPpuccin Obsidian theme. A photographic backdrop shows through at full strength in the margins and faintly behind the reading panel itself; the panel's own translucency is tuned so body text still clears WCAG's 4.5:1 minimum against the darkest or lightest pixel any shipped photo could put behind it. A reader whose OS asks for maximum contrast gets the flat surface back with no photo at all.

### Where your edits actually live

**This is worth understanding, because it is not what you would assume.**
Every keystroke saves **instantly to your browser's local storage**, keyed to
that transcript, regardless of anything below - close the tab, reopen the
file, and your work is there. What differs is whether anything also reaches
the `.html` file itself, and that depends on your browser.

- **Chrome, Edge, and other browsers with the File System Access API:** the
  button reads **"Save"**. The first time you press it (or `Ctrl+S`), it asks
  you to pick a file to write to; every Save after that - including
  autosave, on the same 400ms debounce as the browser-only save - writes
  straight to that file, no dialog. `Ctrl+Shift+S` ("Save a copy") always
  asks for a different file instead, without changing where plain Save
  writes.
- **Firefox and any other browser without that API:** the button reads
  **"Save a copy"**. Pressing it (or `Ctrl+S`/`Ctrl+Shift+S`, which do the
  same thing here) downloads a fresh, fully self-contained copy with every
  edit baked in - the `.html` on disk is never touched directly. That
  download is itself a working editor.

**One prompt per browser session, and it cannot be avoided.** A `file://`
document loses its file permission the moment it reloads - by design, not a
bug in this app - so even the *same* file, chosen in a *previous* session,
needs one more click through the browser's own permission prompt before the
first Save of a new session can write to it. After that click, autosave
writes to disk silently for the rest of that session.

The practical consequence: until you have pressed Save at least once in a
given browser, edits live only in that browser. Emailing the original
`.html` to someone, or opening it on another machine, will not carry them -
Save (or Save a copy) first. Re-running transcription on the same audio also
produces a new document with a new identity, so its predecessor's saved
edits no longer apply to it.

If a file in a batch fails to transcribe, its section says so and every other
file's transcript is still produced - one bad recording doesn't cost you the
rest of the batch. The output file itself is rewritten after every file
finishes, not just once at the very end, so a crash, reboot or power loss
partway through - say, at file 9 of 10 - still leaves the nine completed
transcripts on disk, ready to open.

## Speaker identification

Enabled by default, with a speaker count you can set on the model screen.
Telling it exactly how many people are in the recording matters: fixing the
count is considerably more reliable than letting the app infer it.

Two paths, chosen automatically:

- **One speaker per channel** (some phone and VoIP call recorders): each channel is transcribed separately, so attribution is exact. Detection is strict, since most stereo audio is really a duplicated mono mix. This roughly doubles transcription time.
- **Single microphone**: neural diarization via [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), running offline with no account required. Model weights (~36 MB) download once on first use. Adds roughly a third of the audio's duration to processing time.

If speaker identification fails for any reason, the transcript is still saved - just without labels.

## Correcting names and jargon

Words the model reliably mangles - people, places, organisations,
professional vocabulary - can be listed in a `hebrew_terms.txt` file next to
where you run the app. Copy
[`hebrew_terms.example.txt`](../hebrew_terms.example.txt) to get started.
Without that file, nothing happens.

Only words the model itself flagged as uncertain are considered, and only
your listed terms are candidates. Matching is aware of how Hebrew is actually
misheard (א/ע, כ/ק, ט/ת) and of prefixes, so listing `ירושלים` also covers
`בירושלים`. Every substitution is written to `speech_to_text.log` so you can
check it.

This is not a spell checker, and adding ordinary vocabulary makes it worse
rather than better - see the comments in the example file for why.
