# Manual checks for the transcript document

## Why this file exists

The generated transcript is a small application: it edits, autosaves, renames speakers, searches,
plays audio and exports itself. A jsdom behavioural suite (`tests/js/*.test.mjs`, run via
`node --test` and wrapped by `pytest` - see the README's Testing section) now covers most of that
JavaScript: editing, autosave, speaker renaming/reassignment, search, the plain-text panel, theme
toggling, the help panel and the guided tour.

What that suite structurally cannot cover is anything that depends on real layout: jsdom lays out
no page at all, and stubs `window.matchMedia` to "no preference" unconditionally. So responsive
breakpoints, the tour spotlight ring's actual on-screen geometry, and every `prefers-contrast` /
`prefers-reduced-motion` / dark-mode media query are still browser-only concerns - checked here,
not in `tests/js/`. The Python suite, separately, covers what Python can honestly assert about a
generated document - markup, data payload, escaping, the offline guarantee, and WCAG colour
contrast in both schemes. Neither suite can tell you whether typing in a card actually saves, or
whether a spotlight ring visually lands on its target at 1400px. This checklist is that remaining
gap, written down rather than left implicit. Work it before shipping a change to `core/assets/js/`
or `core/assets/css/`.

**The trap that will waste your time:** the CSS and JS are *inlined at render time*, and each is
now a directory of numbered fragments (`core/assets/js/00-preamble.js` ... `99-init.js`,
`core/assets/css/00-tokens.css` ... `90-responsive.css`) concatenated in sorted order by
`_asset_dir()` in `core/formatting/assets.py`. Editing a fragment does nothing to an HTML file that
already exists. Regenerate before testing.

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

- [ ] Click into a sentence card and type. The status pill goes to "שומר…" then **"נשמר בדפדפן"**.
- [ ] **Reload the page. Your text is still there.** If this fails, nothing else matters -
      localStorage is unavailable on `file://` in this browser and the whole autosave design needs
      revisiting rather than patching.
- [ ] Close the tab entirely, reopen the file. Text still there.
- [ ] Type into a card, then look at its number and timestamp. Neither can be typed over or
      backspaced away - they are `contenteditable="false"` inside an editable card, and an edit
      that ate them would be persisted.
- [ ] Paste formatted text (from Word, or a web page) into a sentence card. It arrives as plain text - no
      fonts, colours or markup follow it in.
- [ ] Edit a card, then try to close the tab. The browser warns about leaving.

## 2. Speaker names, colours and reassignment

Speaker management lives in the outline sidebar now, not inline above each recording's cards - see
section 10 below for the sidebar itself.

- [ ] Type a name in a speaker row in the sidebar. Every card by that speaker updates as you type.
- [ ] Clear the name. It falls back to "דובר 1", not to blank.
- [ ] With two or more files: rename in one, confirm the others are untouched.
- [ ] Press "use these names in all files". Other files' sidebar **name inputs** show the name (not
      just each card's own chip) - but a two-speaker recording does not gain a third name from a
      three-speaker one.
- [ ] Press "+ הוספת דובר" (add speaker). A new row appears with its own name field and colour
      picker, defaulting to a fallback like "דובר 3" that no other speaker in the file is using.
- [ ] Click a swatch on any speaker's colour picker (an existing or a newly added one). That
      speaker's name, every one of their cards' accent stripe, and the swatch's own selected ring
      all update together.
- [ ] **The swatch bug fix**: open a speaker's colour menu, pick the *last* colour in the grid.
      Reopen any colour menu (that speaker's or another's) - it must still show all eight swatches
      in eight visibly distinct colours, not the picked colour repeated across every dot.
- [ ] Open a speaker's colour menu from a row scrolled to the sidebar's **bottom edge** (scroll the
      outline panel so the row sits right at the bottom before opening it, rather than mid-panel).
      The swatch grid must be fully visible, not clipped by the sidebar's own scrollbar. The sidebar
      is a scroll container, so a menu opened mid-panel proves nothing about clipping - only one
      opened at the edge does.
- [ ] Click a card's speaker chip. A menu of every speaker in that file opens, each with its
      current colour and name, plus a choice of scope: this sentence, or the whole block.
- [ ] Choose a different speaker for **one sentence**. That card's stripe and chip change
      immediately; its neighbours do not move. **The plain-text panel regroups**: the reassigned
      line breaks out under its own speaker heading, and the original speaker resumes after it.
- [ ] Choose **the whole block** instead. Every card sharing that block moves together, and
      nothing outside it changes.
- [ ] Reassign a sentence back to the speaker it started as. The override clears and the
      plain-text sections merge back into one heading, rather than leaving two identical headings.
- [ ] Reassign the **last** sentence of a run to the speaker of the run below it. The two must
      **merge** into one section, not produce two consecutive identical headings.
- [ ] Open a reassignment menu on a card that has another card below it, then **move the pointer
      away from the card entirely** before checking - do not leave it hovered. The menu must still
      paint above the card underneath it. This is the critical detail: a fix keyed to `.turn:hover`
      passes with the pointer still resting on the card (hover's own lift already creates a stacking
      context) but fails in real use, because the menu stays open well after the pointer leaves it.
- [ ] A speaker row in the sidebar is just a colour swatch and a name input now - no locate button
      and no turn count next to it (both were removed as clutter, not relocated elsewhere).
- [ ] **Reload the page.** Added speakers, their colours, and any reassigned sentences are all still
      there, exactly as left - not just the text edits.

## 3. Uncertain words

- [ ] Toggle "מילים לא ודאיות". Low-confidence words gain a tint **and** a dotted underline.
- [ ] Hover one: the tooltip shows the confidence.
- [ ] **Edit a shaded card. Its shading disappears** and does not come back on re-toggle - the
      confidence described the model's output, not what you just typed.
- [ ] Toggle off. No leftover markup, no stray spacing.

## 4. Audio

Requires the transcript to be sitting next to its real audio file.

- [ ] Click a card's timestamp. The player appears and playback starts from that point, and the
      range it plays is **that one sentence** - not the whole speaker block.
- [ ] Two adjacent cards play different ranges. If they play the same audio, the per-sentence
      spans derived from word timings have collapsed and nothing else in this section is meaningful.
- [ ] Press any control on a card (play, speaker chip, copy) and then move the pointer away. The
      card must **not** stay visually raised. The lift is a hover affordance; a card left lifted
      because something inside it holds focus reads as a stuck button.
- [ ] **Playback stops at the end of the range**, close to the moment it names (bounded by the
      browser's own `timeupdate` cadence, roughly a quarter second) - it does not run on into the
      next sentence.
- [ ] Press the player's own play/pause toggle while a ranged playback is stopped, or while one is
      still running. Playback resumes and keeps going past the sentence's end - the range only bounds
      the click that started it, not the transport controls.
- [ ] The card being spoken is highlighted, and the highlight moves as playback continues.
- [ ] Pause. The highlight clears.
- [ ] **Move the HTML away from its audio and reload.** Click a timestamp: the player does not
      appear, and that section's timestamps become plain grey labels, not-focusable by Tab.
- [ ] In a batch where only one file's audio is missing: **the other recordings still play.** A
      single bad file must not disable the whole document.
- [ ] The player shows a seek bar and a "current / total" readout. Dragging the seek bar moves
      playback to that position; the readout updates as you drag, not only after you release.
- [ ] **The seek fill advances left to right** as playback runs, even though the page itself is
      RTL - watch the filled (accent-coloured) portion of the track grow from the start edge toward
      the end edge, not the reverse. Drag the thumb by hand too: the fill must track the thumb, not
      lag a tick behind it.
- [ ] Click a timestamp whose range ends before the file's end, let it play to the range's end
      (player pauses there, per the check above), then drag the seek bar to a point *past* that
      original range end. Playback must **not** snap back - a deliberate seek clears the range
      bound the same way pressing the play/pause toggle already does.
- [ ] Click a timestamp. The readout updates to that sentence's start time immediately, before playback
      has produced a single `timeupdate` event.
- [ ] The player's toggle button shows a **pause** glyph while audio is playing and a **play**
      glyph while it is not - including when playback stops on its own (the range-bound stop at a
      sentence's end, per the check above), not only after clicking the toggle itself. Inspect the
      button's accessible name (e.g. via the browser's accessibility tree) alongside the glyph: it
      must say "pause" while playing and "play" while paused, not the same text throughout.

## 5. Search

- [ ] Press `/`. Focus moves to the search box.
- [ ] Press `/` while the caret is inside a sentence card. A literal "/" is typed - search is not hijacked.
- [ ] Type a word. Matches highlight, the counter reads "n / total".
- [ ] Enter and Shift+Enter step forward and back, scrolling each match into view.
- [ ] Search a word written with nikud, or one ending in a final letter form (ם / ן / ץ). It still
      matches the unpointed / non-final spelling.
- [ ] Esc clears the highlights.

## 6. Plain text panel

The panel is one line per **sentence** now, keyed to the card above it, with a speaker heading
inserted wherever the effective speaker changes. It is not one row per speaker block any more -
that older shape could not put a heading in the middle of a block, which is exactly what a
mid-block reassignment produces.

- [ ] It is visible on page load, with no click needed to reveal it - not collapsed behind a
      summary line.
- [ ] The text matches the cards above, including your edits, speaker names and reassignments.
- [ ] Each line reads `1. [0:00 - 0:02] ...` - a number, **a dot**, then a bracketed range.
- [ ] **The dot sits to the LEFT of its number**, between the number and the Hebrew. This is RTL:
      the number is at the right edge and the text runs leftward, so a dot painted to the number's
      right is on the wrong side. Zoom in if unsure - it is one character and easy to skim past.
- [ ] Numbering runs continuously across speaker changes, and restarts at 1 for the next file.
- [ ] Consecutive ranges never overlap, and none reads `0:00 - 0:00`.
- [ ] A speaker heading appears once per run of consecutive sentences by that speaker - not once
      per block, so a speaker whose block was split by a pause still gets a single heading.
- [ ] Uncheck "חותמות זמן" - the ranges disappear and the numbering stays. Uncheck
      "שמות דוברים" - the headings disappear. Both update immediately and survive a reload.
- [ ] Render a transcript with timestamps **off** and open it. The "חותמות זמן" checkbox must
      start **unchecked**. If it starts checked, the page rebuilds itself on load and invents
      ranges the renderer deliberately omitted.
- [ ] "העתקת הכול" copies. Paste into another app: the Hebrew reads correctly, timestamps are not
      reversed, each range is bracketed, and **the whole paragraph is right-aligned**. Left
      alignment means the invisible RTL mark that anchors each copied line is missing - apps guess
      paragraph direction from the first strong character, and every line now opens with a number.
- [ ] A toast appears near the bottom confirming the copy, and disappears on its own after a few
      seconds. A per-card copy button does the same, alongside its own brief flash.
- [ ] A per-card copy gives the sentence with its timestamp and speaker, and **no line number** -
      the number belongs to the panel, not to the sentence.
- [ ] Edit a card with the panel open. The panel updates without any action on your part, **and the
      caret in whatever else you were typing (another card, the search box) is undisturbed.**
- [ ] **Two-way editing.** Click directly into a line in the panel and type. The matching card
      above updates as you type - reload and the edit is still there.
- [ ] Edit a panel line, then look at the card. The `1. [0:00 - 0:02]` lead-in must **not** have
      been written into the card's text. If it has, every future edit through the panel bakes a
      stale number and a stale timestamp into the transcript permanently.
- [ ] Type in a panel line and don't stop: the caret must stay put mid-word. This is the
      re-entrancy guard - editing here must not trigger a rebuild that yanks the caret away.
- [ ] Paste formatted text into a panel line. It arrives as plain text only, same as a card.

## 7. Export

- [ ] Press "שמירת עותק" (or `Ctrl+S`). A file downloads and the status changes to "נשמר".
- [ ] **Open the downloaded copy.** It contains your edits, speaker names, any added speakers and
      their colours, and any reassigned sentences; the speaker name boxes are filled in (not empty),
      search is not mid-query, and no player is stuck on screen.
- [ ] Edit the downloaded copy and reload it. Its own edits persist - it is a working editor, not a
      snapshot.
- [ ] Export with the uncertain-words toggle on. The exported file has no shading baked into it.

## 8. Appearance and access

- [ ] Toggle the theme. Both schemes are readable; the choice survives a reload.
- [ ] Set the OS to dark mode with no in-page choice made. The document follows it.
- [ ] The reading panel (.source, .outline, menus) is visibly distinct from the page ground in both
      schemes - a flat, raised surface, not flush with the body colour behind it.
- [ ] **Backdrop legibility over a dark-heavy vista (Phase 5/5b).** Generate a document pinned to a
      vista that genuinely contains pure-black pixels - vista-09, -29, -30 and -31 all do, and that is
      the case that makes *light* mode's contrast tightest, not dark mode's:

      ```bash
      py -3.11 -c "
      import io, sys; sys.path.insert(0, '.')
      from speech_to_text.core import formatting; formatting._asset.cache_clear()
      from speech_to_text.core.segments import Segment, TranscriptDocument, Word
      from speech_to_text.gui import i18n; i18n.set_language('he')
      w = lambda t, p: Word(start=0, end=1, text=t, probability=p)
      segs = [Segment(0, 5, 'שלום, מה שלומך היום?', speaker=0,
                      words=[w('שלום,', .99), w('מה', .98), w('שלומך', .41), w('היום?', .93)])]
      io.open('check-dark-vista.html', 'w', encoding='utf-8').write(formatting.render_html(
          [TranscriptDocument('meeting.m4a', segs)], speaker_label=i18n.t('speaker_label'),
          title='check', ui_strings=i18n.document_strings(), vista='vista-09.webp'))
      "
      ```

      Open it in both colour schemes. The photo is visible at full strength in the margins and
      faintly through the reading panel (.source, .outline, .file-bar) where text sits, and every
      line of body text and every timestamp/muted label stays comfortably legible over the darkest
      part of the photo, in both schemes - not just plausible-looking, but readable at a normal
      glance without straining.
- [ ] Set the OS to "prefers contrast: more". The backdrop photo disappears entirely (a reader who
      asked for maximum contrast should not have a photo behind their text at all).
- [ ] Scroll a file with several cards. Its filename bar stays pinned just below the toolbar the
      whole way through that file, with its own accent colour, and hands off to the next file's bar
      at the section boundary rather than overlapping it.
- [ ] Tab through the whole page, including a card's speaker chip and its reassignment menu, and
      the colour swatches in the speakers strip. Focus is always visible, and the tab order follows
      the reading order.
- [ ] **Focus ring, keyboard-only (Phase 7).** Click directly into a card's sentence text, and separately
      into a row in the plain-text panel, to place the caret and select some text. **No ring appears
      on either**, even though the caret and any selection are visible. Then press Tab until focus
      reaches a card and, separately, a plain-text row: **a ring appears** on each - one clean box on
      the card, not a per-line staircase on the plain-text row. `.speaker-name` is out of scope; its
      focus cue is unchanged either way. Click a toolbar button, or focus `#search`, and confirm both
      keep exactly today's behaviour (a button still rings; the search box still shows only its
      accent underline, never a ring).
- [ ] Turn on "reduce motion" at the OS level. Cards no longer lift on hover, the colour-swatch hover
      scale is gone, the toast still appears/disappears but without sliding, and search does not
      smooth-scroll.
- [ ] Narrow the window to ~375px. No horizontal scrolling, and the per-card copy buttons are
      permanently visible rather than hover-only.
- [ ] **The reading column stays centred as the window narrows.** At 1900px, 1400px, 1100px and
      900px, `<main>`'s centre matches the viewport centre, and the toolbar's first control shares
      an edge with the reading column. This guards a specific regression, not a taste preference:
      `.toolbar` and `.layout` used to be two independently centred boxes of different widths -
      156px apart at the values then in play - so nothing "pushed" one off from the other; they were
      simply never tied to the same measurement. Lining them up here is a guarantee now, not a
      coincidence of today's numbers.
- [ ] On a touch device or with hover emulation off: every control is reachable without hovering,
      including the speaker colour swatches and the add-speaker button.

## 9. Outline sidebar

Best tested with a multi-file batch (three recordings is enough) so there is something for the
"current file" tracking to actually show.

- [ ] The sidebar lists every file and shows the current file's speakers panel. On a single-file
      document with no speakers to manage, the sidebar (and its toolbar button) are absent entirely.
- [ ] Scroll through the document. The file list's current-file marker, and which file's speakers
      panel is shown, both track which file you are actually reading - not just which one you
      started on.
- [ ] Click a file name in the sidebar. The view jumps to that file's section.
- [ ] Narrow the window below ~1200px - not the old ~900px, which was measured against a fixed-width
      sidebar; the current sidebar's flanks are flexible and get squeezed well before 900px. The
      sidebar disappears behind a toolbar button, **and that button appears at this width and not
      before** (it is not present in the toolbar above the breakpoint). Clicking it opens the
      sidebar as an overlay over the transcript.
- [ ] With the overlay open, press Escape. It closes, and focus returns to the toolbar button.
- [ ] With the overlay open, press Tab repeatedly past its last focusable element. Focus leaves the
      overlay and continues into the rest of the page - it must not be trapped inside.
- [ ] With JavaScript disabled (or before it has finished loading): the transcript's own cards are
      still fully readable regardless of window width - only the sidebar's file-jump and
      speaker-management conveniences are affected.

## 10. Crash recovery

This is a worker-process check, not a transcript JS one: the output HTML is rewritten after every
file in a batch finishes, not only once at the very end, since transcription is by far the most
expensive step in the pipeline and a crash near the end of a long batch used to lose the whole run.

- [ ] Start a batch of three or more files. **After the second file finishes** (watch the progress
      log, or just time it), kill the app outright - end the process, do not use the app's own
      Cancel button.
- [ ] An HTML file already exists on disk at the batch's output location, containing the completed
      transcripts for however many files finished before the kill.
- [ ] Open it. It behaves exactly like a normal, complete transcript - editing, autosave, search,
      speaker management, all as expected. A checkpoint file is a real document, not a partial or
      broken one.

## 11. Offline guarantee

- [ ] Disconnect from the network entirely and open the file. Everything works, nothing is missing,
      and the browser's network tab shows no requests.

## 12. Help panel and guided tour

`#help` and the tour it launches are the one part of the page with no server-rendered fallback for
the tour's own overlay (`.tour-scrim`/`.tour-ring`/`.tour-card`) - the whole feature is built by
`bindHelp()`/`startTour()` in `core/assets/js/88-help-tour.js`. The help panel's markup and copy
*are* server-rendered (see `_render_help_html()`), but do nothing until script binds them - same
"readable without JavaScript, but the interaction is scripted" contract as the rest of this page.

### Help panel

- [ ] Click the toolbar's "עזרה" button. The panel opens over a dim scrim, `aria-expanded` on the
      button flips to `"true"`, and focus lands on the panel's own close button (not left on the
      toolbar button, and not on the panel's first list entry).
- [ ] Every control the toolbar and reading column actually have is listed, each with a plain
      explanation - nothing missing, nothing describing a control that doesn't exist.
- [ ] Click the close button (✕). The panel closes, `aria-expanded` returns to `"false"`, and focus
      returns to the "עזרה" button - not lost to `<body>`.
- [ ] Reopen the panel and click on the dim scrim itself, well outside the white sheet. It closes the
      same way. Click *inside* the sheet, anywhere that isn't a button - it must **not** close.
- [ ] Reopen the panel and press **Escape**. It closes, same focus-return behaviour as the close
      button.
- [ ] Reopen the panel and press **Tab** repeatedly. Focus cycles only through the panel's own
      controls (close button, "התחלת סיור מודרך", nothing else is focusable inside it) - it must
      never leave the panel into the toolbar or the page behind it. **Shift+Tab** from the first
      control wraps to the last, not out of the panel.
- [ ] Resize the window short enough that the help list overflows. The sheet itself scrolls
      internally; the page behind the scrim does not move.

### Guided tour

- [ ] With a multi-file batch that has timestamps and detected speakers, open help and click
      "התחלת סיור מודרך". The help panel closes, and the tour's first step (the sticky file bar)
      opens immediately - no second click needed.
- [ ] **Step through with Next.** Each step spotlights a different real control (file bar → sidebar →
      search → speaker roster → a timestamp → a card's text → "הצגת מילים לא ודאיות" → "שמירת
      עותק"), scrolling it into view and dimming everything else. The counter reads "n / total" and
      the total matches however many of those controls this particular document actually has - not a
      hardcoded 8.
- [ ] **Regenerate a document that omits something** - a single file (no `.outline`), no detected
      speakers (no `.speakers` strip), or `timestamps=False` (no `.ts` buttons) - and start the tour
      again. The missing step is silently absent; the counter's total shrinks to match, and nothing
      errors or shows a blank spotlight.
- [ ] Click **Back** on any step after the first. It returns to the previous step's spotlight. Back
      is hidden entirely on the first step.
- [ ] Click **Skip** partway through. The tour ends immediately (not just "jump to the last step"),
      and focus returns to the "עזרה" toolbar button.
- [ ] Start the tour again and press **Escape** mid-tour. Same clean end as Skip.
- [ ] Finish the tour normally (Next through the last step, whose button reads "סיום" rather than
      "הבא"). Same clean end, focus back on "עזרה".
- [ ] **Resize the window while a step is showing.** The spotlight ring and the caption card both
      re-follow the target's new position rather than staying put or drifting off it.
- [ ] **Scroll the page while a step is showing** (drag the scrollbar, or spin the wheel) rather than
      letting the tour's own `scrollIntoView` do it. Same result - the ring tracks the target.
- [ ] **The non-destructive check, the one that matters most.** Open a freshly generated document
      (reload from disk, not a tab you have already edited in), confirm the status pill reads
      "נשמר", then run the entire tour start to finish - every step, Next all the way through,
      including the two steps that spotlight a timestamp and a card's editable text. Afterwards:
      - [ ] The status pill still reads **"נשמר"**, not "שומר בדפדפן" - nothing was saved.
      - [ ] No player appeared and no audio played, even though one step points directly at a
            timestamp button.
      - [ ] No text changed anywhere on the page, even though one step points directly at an
            editable card.
      - [ ] No speaker menu or colour popover is left open, and no speaker was renamed or
            recoloured.
      - [ ] "הצגת מילים לא ודאיות" is still off (`aria-pressed="false"`) even though a step
            explains what it does.
      - [ ] Reload the page. There is nothing to restore - the tour left no trace in localStorage.
- [ ] **Focus trap.** During any step, press Tab repeatedly. Focus cycles only through the caption
      card's own Skip/Back/Next buttons (Back excluded when hidden), never escaping to the dimmed
      page behind the scrim.
- [ ] **Click something on the dimmed page** during a step - including a click squarely on the very
      control the current step is pointing at (a timestamp, a card's text, the flags toggle). Nothing
      happens: the scrim absorbs the click before it reaches the page.
- [ ] **RTL.** The caption card sits sensibly beside or below its target with the whole layout still
      right-to-left - button order (Skip / Back / Next) and text alignment read naturally, not
      mirrored oddly or overflowing the viewport's edge for a wide target like the file bar or the
      sidebar.
- [ ] **Dark mode.** Toggle the theme, then run the tour. The scrim, ring outline and caption card are
      all legible against the dark palette - no washed-out ring, no unreadable caption text.
- [ ] **`prefers-contrast: more`.** The caption card and ring both gain a visibly thicker edge, the
      same "more contrast, please" treatment `.help-sheet` gets.
- [ ] **`prefers-reduced-motion: reduce`.** Step through the tour. The spotlight and card reposition
      instantly with each Next/Back - no sliding or fading - and `scrollIntoView` jumps rather than
      smooth-scrolling to each target.
- [ ] **Start the tour, skip it, then start it again.** No leftover scrim/ring/card from the first run
      double-painted under the second, and stepping through the second run works exactly like the
      first (confirms cleanup actually removed every element and listener, not just visually hid
      them).

---

## Known limitations, deliberately

- Edits live in the browser they were made in until exported. Emailing the original `.html` does
  not carry them.
- Re-running transcription overwrites the file and produces a new document identity, so the
  previous document's saved edits no longer apply. Export first if they matter.
- Sentence structure is fixed once rendered: text and speaker attribution are editable, but
  sentences cannot be merged, split or re-timed in the page. Splitting happens server-side, where a
  segment whose words cross a speaker boundary is cut at that boundary before the page is built
  (see `assign_speakers` in `core/diarization.py`); the page can only move a sentence to a
  different speaker, not change where one sentence ends and the next begins.
