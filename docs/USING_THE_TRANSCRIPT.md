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
- **Fix what the model doubted.** Whisper records a confidence for every word, and the ones below the threshold the Hebrew term-correction pass uses are highlighted as soon as the transcript opens (the toolbar toggle turns that off, and the choice sticks). This is the difference between re-reading a whole transcript and looking at the twenty words that need it. Click one - or Tab to it and press Enter - and a menu opens right under it: the terms from your list it may have been (pick with 1-3), a field for the right word, or "keep as is". A word the app already corrected from your term list has a solid underline instead, and its menu offers the original back. A pick changes only that word, so the card's other highlights stay; typing in a card turns it into ordinary edited text and clears its highlights, because the confidence no longer describes what is now there.
- **Listen exactly to a turn.** The transcript is written next to its audio, so clicking a timestamp seeks, plays, and pauses again at the turn's end - and the turn being spoken is highlighted while it plays. The player has its own seek bar and a "current / total" readout; dragging the seek bar past a turn's end plays on rather than snapping back, the same way pressing play/pause already overrides a turn's bounds. If the audio is moved away or is in a container the browser can't play, that recording's timestamps quietly become plain labels - the rest of the batch is unaffected.
- **Search** across every file with `/`, stepping through matches with Enter. Matching ignores nikud and treats final letter forms as the same letter.
- **Copy it out, and edit from either side.** Every section has an always-visible plain-text panel with checkboxes for timestamps and speaker names, plus a per-turn copy button. It is not read-only: each row is itself editable and tied to its card, so a fix typed into the plain-text panel updates the card above it, and vice versa - there is nothing to keep in sync by hand. Every copy - a turn or the whole panel - confirms itself with a brief toast.
- **Keep your place in a batch.** Each file's name stays pinned below the toolbar as you scroll through it, in its own accent colour, and the sidebar's file list and speaker panel track the same thing, so it's hard to drift from one recording's turns into the next one's without noticing.
- **Light or dark, following your system.** The document defaults to your OS colour scheme, with its own toggle to override that. The palette is based on Catppuccin (Latte for light, Mocha for dark) - the same basis as the AnuPpuccin Obsidian theme. A photographic backdrop shows through at full strength in the margins and faintly behind the reading panel itself; the panel's own translucency is tuned so body text still clears WCAG's 4.5:1 minimum against the darkest or lightest pixel any shipped photo could put behind it. A reader whose OS asks for maximum contrast gets the flat surface back with no photo at all.

### Where your edits actually live

Every keystroke saves instantly to your browser's local storage, whatever
browser you are in. Whether it also reaches the `.html` file on disk depends
on which one:

- **Chrome or Edge:** the button reads **"Save"**. The first press each time
  you open the document asks the browser's permission to write the file;
  after that, autosave writes straight to it with no further dialog.
  `Ctrl+Shift+S` saves a copy elsewhere without changing where Save writes.
  The repeated prompt is the browser's rule, not ours - a `file://` page
  loses its file permission on every reload.
- **Firefox:** the button reads **"Save a copy"** and downloads a fresh
  self-contained copy, which is itself a working editor. Firefox has no API
  for writing the file in place, so the original is never touched.

Until you press Save at least once, your edits live only in that browser -
emailing the original `.html` or opening it elsewhere will not carry them.
Re-running transcription on the same audio produces a new document with a new
identity, so the old one's saved edits no longer apply to it.

If a file in a batch fails to transcribe, its section says so and every other
file's transcript is still produced - one bad recording doesn't cost you the
rest of the batch. The output file itself is rewritten after every file
finishes, not just once at the very end, so a crash, reboot or power loss
partway through - say, at file 9 of 10 - still leaves the nine completed
transcripts on disk, ready to open.

## Speaker identification

On by default. Set how many people are in the recording with the − / +
buttons in the **Speakers** panel on the model screen; set it to 1 to skip
speaker identification entirely. Telling it the exact count matters: fixing
the count is considerably more reliable than letting the app infer it.

Two paths, chosen automatically:

- **One speaker per channel** (some phone and VoIP call recorders): each channel is transcribed separately, so attribution is exact. Detection is strict, since most stereo audio is really a duplicated mono mix. This roughly doubles transcription time.
- **Single microphone**: neural diarization via [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), running offline with no account required. Model weights (~36 MB) download once on first use. Adds roughly a third of the audio's duration to processing time.

If speaker identification fails for any reason, the transcript is still saved - just without labels.

## Correcting names and jargon

Words the model reliably mangles - people, places, organisations,
professional vocabulary - go in the **Custom terms** panel on the model
screen: press **Edit**, type a term and press Enter. The panel shows how many
terms you have and the first few of them. The list is saved as
`hebrew_terms.txt` in the app's folder (hover **Edit** for the exact path)
and stays editable by hand;
[`hebrew_terms.example.txt`](../hebrew_terms.example.txt) explains the
format. With no terms, nothing happens.

Only words the model itself flagged as uncertain are considered, and only
your listed terms are candidates. Matching is aware of how Hebrew is actually
misheard (א/ע, כ/ק, ט/ת), of prefixes - listing `ירושלים` also covers
`בירושלים` - and of punctuation attached to a word. A two-word term such as
`יובל קוגן` is matched against two words together, and only the doubted one
may differ. A word the same recording shows the model writing confidently
elsewhere is never replaced: otherwise a list holding `ענבל` turns `אבל`
("but") into the name. Every substitution is written to `speech_to_text.log`,
and the transcript's fix menu can restore any of them.

What to expect, measured on three real recordings with human transcripts:
Ivrit Turbo, the default, already wrote almost every name right, and the few
it missed it missed confidently - out of reach of any correction afterwards.
On the smaller models, whose mistakes are more often uncertain ones, the same
list fixed six names and broke no correct word.
`tests/eval/compare_term_correction.py` reruns the measurement.

This is not a spell checker, and adding ordinary vocabulary makes it worse
rather than better - see the comments in the example file for why.
