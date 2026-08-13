# Manual checks for the transcript document

## Why this file exists

The generated transcript is a small application: it edits, autosaves, renames speakers, searches,
plays audio and exports itself. **None of that JavaScript is covered by automated tests.** This
project has no JS test runner, and adding jsdom or vitest would be a larger change than the feature
it would be testing.

The Python suite covers what Python can honestly assert about a generated document - that the
markup, data payload, escaping, offline guarantee and colour contrast are correct. It cannot tell
you whether typing in a card actually saves. This checklist is that gap, written down rather than
left implicit. Work it before shipping a change to `core/assets/transcript.js` or
`core/assets/transcript.css`.

**The trap that will waste your time:** the CSS and JS are *inlined at render time*. Editing
`transcript.js` does nothing to an HTML file that already exists. Regenerate before testing.

Generate a document to test against:

```bash
py -3.11 -c "
import io, sys; sys.path.insert(0, '.')
from speech_to_text.core import formatting; formatting._asset.cache_clear()
from speech_to_text.core.segments import Segment, TranscriptDocument, Word
from speech_to_text.gui import i18n; i18n.set_language('he')
w = lambda t, p: Word(start=0, end=1, text=t, probability=p)
segs = [Segment(0, 5, 'שלום, מה שלומך היום?', speaker=0,
                words=[w('שלום,', .99), w('מה', .98), w('שלומך', .41), w('היום?', .93)])]
io.open('check.html', 'w', encoding='utf-8').write(formatting.render_html(
    [TranscriptDocument('meeting.m4a', segs)], speaker_label=i18n.t('speaker_label'),
    title='check', ui_strings=i18n.document_strings()))
"
```

Then **open `check.html` by double-clicking it**. Do not serve it over localhost: `file://` is the
only origin that matters here, and it is the one with the restrictions.

---

## 1. Editing and autosave

- [ ] Click into a turn and type. The status pill goes to "שומר…" then **"נשמר בדפדפן"**.
- [ ] **Reload the page. Your text is still there.** If this fails, nothing else matters -
      localStorage is unavailable on `file://` in this browser and the whole autosave design needs
      revisiting rather than patching.
- [ ] Close the tab entirely, reopen the file. Text still there.
- [ ] Paste formatted text (from Word, or a web page) into a turn. It arrives as plain text - no
      fonts, colours or markup follow it in.
- [ ] Edit a turn, then try to close the tab. The browser warns about leaving.

## 2. Speaker names, colours and reassignment

- [ ] Type a name in the speakers strip. Every turn by that speaker updates as you type.
- [ ] Clear the name. It falls back to "דובר 1", not to blank.
- [ ] With two or more files: rename in one, confirm the others are untouched.
- [ ] Press "use these names in all files". Other files adopt them - but a two-speaker recording
      does not gain a third name from a three-speaker one.
- [ ] Press "+ הוספת דובר" (add speaker). A new row appears with its own name field and colour
      picker, defaulting to a fallback like "דובר 3" that no other speaker in the file is using.
- [ ] Click a swatch on any speaker's colour picker (an existing or a newly added one). That
      speaker's name, every one of their turns' accent border, and the swatch's own selected ring
      all update together.
- [ ] Click a turn's speaker label. A menu of every speaker in that file opens, each with its
      current colour and name.
- [ ] Choose a different speaker from that menu. The turn's accent border and label change to the
      target speaker immediately, **and the plain-text panel below updates to match** without being
      reopened.
- [ ] **Reload the page.** Added speakers, their colours, and any reassigned turns are all still
      there, exactly as left - not just the text edits.

## 3. Uncertain words

- [ ] Toggle "מילים לא ודאיות". Low-confidence words gain a tint **and** a dotted underline.
- [ ] Hover one: the tooltip shows the confidence.
- [ ] **Edit a shaded turn. Its shading disappears** and does not come back on re-toggle - the
      confidence described the model's output, not what you just typed.
- [ ] Toggle off. No leftover markup, no stray spacing.

## 4. Audio

Requires the transcript to be sitting next to its real audio file.

- [ ] Click a timestamp. The player appears and playback starts from that point.
- [ ] **Playback stops at the end of the range**, close to the moment it names (bounded by the
      browser's own `timeupdate` cadence, roughly a quarter second) - it does not run on into the
      next turn.
- [ ] Press the player's own play/pause toggle while a ranged playback is stopped, or while one is
      still running. Playback resumes and keeps going past the turn's end - the range only bounds
      the click that started it, not the transport controls.
- [ ] The turn being spoken is highlighted, and the highlight moves as playback continues.
- [ ] Pause. The highlight clears.
- [ ] **Move the HTML away from its audio and reload.** Click a timestamp: the player does not
      appear, and that section's timestamps become plain grey labels, not-focusable by Tab.
- [ ] In a batch where only one file's audio is missing: **the other recordings still play.** A
      single bad file must not disable the whole document.

## 5. Search

- [ ] Press `/`. Focus moves to the search box.
- [ ] Press `/` while the caret is inside a turn. A literal "/" is typed - search is not hijacked.
- [ ] Type a word. Matches highlight, the counter reads "n / total".
- [ ] Enter and Shift+Enter step forward and back, scrolling each match into view.
- [ ] Search a word written with nikud, or one ending in a final letter form (ם / ן / ץ). It still
      matches the unpointed / non-final spelling.
- [ ] Esc clears the highlights.

## 6. Plain text panel

- [ ] It is visible on page load, with no click needed to reveal it - not collapsed behind a
      summary line.
- [ ] The text matches the cards above, including your edits, speaker names and reassignments.
- [ ] Uncheck "חותמות זמן" and "שמות דוברים" - the text updates immediately.
- [ ] "העתקת הכול" copies. Paste into another app: the Hebrew reads correctly and timestamps are
      not reversed.
- [ ] A toast appears near the bottom of the screen confirming the copy, and disappears on its own
      after a few seconds. A per-turn copy button does the same, alongside its own brief flash.
- [ ] Edit a card with the panel open. The panel updates without any action on your part.

## 7. Export

- [ ] Press "שמירת עותק" (or `Ctrl+S`). A file downloads and the status changes to "נשמר".
- [ ] **Open the downloaded copy.** It contains your edits, speaker names, any added speakers and
      their colours, and any reassigned turns; the speaker name boxes are filled in (not empty),
      search is not mid-query, and no player is stuck on screen.
- [ ] Edit the downloaded copy and reload it. Its own edits persist - it is a working editor, not a
      snapshot.
- [ ] Export with the uncertain-words toggle on. The exported file has no shading baked into it.

## 8. Appearance and access

- [ ] Toggle the theme. Both schemes are readable; the choice survives a reload.
- [ ] Set the OS to dark mode with no in-page choice made. The document follows it.
- [ ] The vista photo is faintly visible through the reading panel in both schemes - it should read
      as "behind the text," not fully masked out and not fighting the text for attention.
- [ ] Scroll a file with several turns. Its filename bar stays pinned just below the toolbar the
      whole way through that file, with its own accent colour, and hands off to the next file's bar
      at the section boundary rather than overlapping it.
- [ ] Tab through the whole page, including a turn's speaker label and its reassignment menu, and
      the colour swatches in the speakers strip. Focus is always visible, and the tab order follows
      the reading order.
- [ ] Turn on "reduce motion" at the OS level. Cards no longer lift on hover, the colour-swatch hover
      scale is gone, the toast still appears/disappears but without sliding, and search does not
      smooth-scroll.
- [ ] Set the OS to "more contrast." The backdrop photo disappears entirely.
- [ ] Narrow the window to ~375px. No horizontal scrolling, and the per-turn copy buttons are
      permanently visible rather than hover-only.
- [ ] On a touch device or with hover emulation off: every control is reachable without hovering,
      including the speaker colour swatches and the add-speaker button.

## 9. Offline guarantee

- [ ] Disconnect from the network entirely and open the file. Everything works, nothing is missing,
      and the browser's network tab shows no requests.

---

## Known limitations, deliberately

- Edits live in the browser they were made in until exported. Emailing the original `.html` does
  not carry them.
- Re-running transcription overwrites the file and produces a new document identity, so the
  previous document's saved edits no longer apply. Export first if they matter.
- Turn structure is fixed: text and speaker names are editable, but turns cannot be merged, split
  or re-timed.
