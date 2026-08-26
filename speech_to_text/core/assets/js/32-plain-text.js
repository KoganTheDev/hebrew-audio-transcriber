  // ------------------------------------------------------------- plain text

  // The card's own pill stays bare ("0:00 - 0:32"): a click target reads its
  // own shape as the label. The plain-text panel gets copied out of the
  // browser into apps with no bidi engine of their own, so it needs the
  // stronger visual cue of brackets - and, per the LRI/PDI comment block in
  // core/formatting, the brackets have to sit *inside* the isolate along
  // with the range, not outside it: they are mirrored characters exactly
  // like the hyphen is a neutral, so a bracket pasted outside the isolate
  // could reorder the same way the old un-isolated timestamps did.
  // PLAIN_LRI/PLAIN_PDI themselves live in the shared preamble fragment now
  // - the guided tour's own step counter needs the same pair.

  function bracketedRange(ts) {
    // ts.textContent already carries format_range()'s own LRI/PDI pair
    // (rendered by core/formatting); stripped here and reapplied around the
    // bracketed form rather than nested, so the plain-text panel still has
    // exactly one isolate pair per range, per the module docstring. Used by
    // bubblePlainText() below, reading a bubble's own rendered .ts range
    // text directly - a different thing from the per-line range
    // rebuildPlain() builds for each sentence (see lineLeadIn() below),
    // which has no rendered .ts to read from when a line is being rebuilt
    // from a bubble's own data-start/data-end rather than copied from an
    // existing element.
    var bare = ts.textContent.trim().replace(/[⁦⁩]/g, '');
    return PLAIN_LRI + '[' + bare + ']' + PLAIN_PDI;
  }

  // Whole-second m:ss / h:mm:ss formatting, mirroring format_mmss()/
  // format_hhmmss() in core/formatting/timecode.py closely enough that
  // formatSentenceRange() below produces byte-identical text to
  // _render_plain_line_html()'s server render. Kept as two small functions
  // rather than one with a branch inside, the same shape the Python side
  // uses (format_mmss/format_hhmmss chosen by format_range()'s own
  // `promote` flag).
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function formatMmss(seconds) {
    var total = Math.max(Math.floor(seconds), 0);
    var m = Math.floor(total / 60);
    var s = total % 60;
    return m + ':' + pad2(s);
  }

  function formatHhmmss(seconds) {
    var total = Math.max(Math.floor(seconds), 0);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return h + ':' + pad2(m) + ':' + pad2(s);
  }

  // A sentence's own "M:SS - M:SS" range, un-isolated (lineLeadIn() below
  // wraps it, together with the number and the dot, in one LRI/PDI pair -
  // see the module docstring on why one isolate, not two). Mirrors
  // format_range() in timecode.py, including its hour-promotion rule (both
  // ends promote together once either passes an hour), except that the end
  // second carries a floor of one second above the start. This MUST stay
  // identical to _display_end_second() in core/formatting/document.py: the
  // server renders these lines and rebuildPlain() regenerates them, so any
  // divergence makes the panel visibly change the first time the reader
  // toggles a checkbox. Read that function's docstring for the reasoning -
  // in short, truncation alone gives "0:00 - 0:00" on a sub-second
  // sentence, and rounding up unconditionally makes consecutive ranges
  // overlap, which reads as a bug and defeats the point of showing a range
  // at all.
  function formatSentenceRange(start, end) {
    var endSecond = Math.max(Math.floor(end), Math.floor(start) + 1);
    var promote = Math.floor(start) >= 3600 || endSecond >= 3600;
    var fmt = promote ? formatHhmmss : formatMmss;
    return fmt(start) + ' - ' + fmt(endSecond);
  }

  // _render_plain_line_html() (core/formatting/document.py) leads every
  // .plain-body with "{LRI}{n}{PDI}. " - or, with timestamps on,
  // "{LRI}{n}{PDI}. {LRI}[{range}]{PDI} " - the number and the range each
  // sit in their OWN isolate, with the dot and the space between them
  // OUTSIDE both. See the docstring on _render_plain_line_html() (Python
  // side) for why: a single isolate around the whole lead-in put the dot to
  // the right of the digit in RTL text - the wrong side, since the dot has
  // to separate the number from what follows it, which reads to the
  // number's LEFT in Hebrew. lineLeadIn() below has to reproduce this same
  // two-isolate lead-in when rebuildPlain() regenerates a line from a
  // bubble's own text, and the panel's own input handler has to strip it
  // back off before that text is ever written back into a bubble's <p> -
  // otherwise the lead-in stops being a display artifact and becomes part
  // of the sentence, permanently, the next time this line is edited.
  var LINE_NUMBER_RE = new RegExp(
    '^' + PLAIN_LRI + '\\d+' + PLAIN_PDI + '\\. '
    + '(?:' + PLAIN_LRI + '\\[[^' + PLAIN_PDI + ']*\\]' + PLAIN_PDI + ' )?'
  );

  function stripLineNumber(line) {
    return line.replace(LINE_NUMBER_RE, '');
  }

  // A bubble's own effective speaker name: its override's, if it has one
  // (paintBubbleOverride() in js/24-speakers-menus.js sets data-override,
  // and the button's own textContent is kept in step by applyNames() - see
  // its widened selector there), otherwise the cluster's own name, passed
  // in by the caller so this never has to re-look-up the same .spk twice
  // for every bubble in a turn.
  function bubbleSpeakerName(bubble, clusterName) {
    if (!bubble.hasAttribute('data-override')) { return clusterName; }
    var btn = bubble.querySelector('.bubble-spk');
    var name = btn ? btn.textContent.trim() : '';
    return name || clusterName;
  }

  // The inverse of stripLineNumber(): lays the same "{LRI}{n}{PDI}. " (or,
  // with withTs, "{LRI}{n}{PDI}. {LRI}[{range}]{PDI} ") lead-in
  // _render_plain_line_html() (core/formatting/document.py) uses ahead of
  // one sentence's own text, so a line rebuilt client-side (a reader typed
  // into the card, an override just moved it into a different run, or the
  // .opt-ts toggle changed) shows the same text a fresh server render
  // would.
  function lineLeadIn(number, start, end, withTs) {
    var lead = PLAIN_LRI + number + PLAIN_PDI + '. ';
    if (withTs) {
      lead += PLAIN_LRI + '[' + formatSentenceRange(start, end) + ']' + PLAIN_PDI + ' ';
    }
    return lead;
  }

  // A turn's cluster-level speaker name, resolved the same way
  // reassignTurn()/paintBubbleOverride() (js/24-speakers-menus.js) resolve
  // one: off the file's own .speaker-row roster, keyed by turn.dataset.speaker.
  // There is no more .spk element to just read textContent off - the
  // cluster header that used to carry one is gone (see the review plan's
  // "flat sentence cards" section) - so this is now the one place that
  // lookup happens for the plain-text panel's own purposes.
  function clusterSpeakerName(turn) {
    var id = turn.dataset.speaker;
    if (typeof id === 'undefined') { return ''; }
    var section = turn.closest('.source');
    var strip = section ? stripFor(section.dataset.file) : null;
    var row = strip && strip.querySelector('.speaker-row[data-speaker="' + id + '"]');
    var input = row && row.querySelector('.speaker-name');
    if (!input) { return ''; }
    return (input.value && input.value.trim()) || input.placeholder || '';
  }

  // One sentence's own copy text - the per-card counterpart to the old
  // per-turn "copy this turn" action, which had no home left once the
  // cluster header (and its .turn-actions) went away. Reads the bubble's
  // OWN chip for its name, which is always populated now (see
  // _render_bubble_html()'s docstring) rather than needing a cluster
  // fallback the way bubbleSpeakerName() does for the plain-panel's
  // headings.
  function bubblePlainText(bubble, withTs, withSpk) {
    var p = bubble.querySelector('p');
    var text = p ? p.textContent.trim() : '';
    var parts = [];
    if (withTs) {
      var ts = bubble.querySelector('.ts');
      if (ts) { parts.push(bracketedRange(ts)); }
    }
    if (withSpk) {
      var labelEl = bubble.querySelector('.bubble-spk-label');
      var name = labelEl ? labelEl.textContent.trim() : '';
      if (name) { parts.push(name + ':'); }
    }
    var head = parts.join(' ');
    return head ? head + ' ' + text : text;
  }

  // Rebuilds the panel's headings and .plain-line elements from the
  // section's bubbles, in document order, one .plain-line per sentence -
  // never a full teardown and rebuild of the panel's innerHTML, which would
  // fight a reader mid-edit by replacing the live line under their caret
  // every time any bubble anywhere in the file changes.
  //
  // The panel is grouped by each sentence's EFFECTIVE speaker, not by which
  // turn it sits in (see the module docstring in document.py's
  // _render_plain_html() for why): a heading is emitted wherever a
  // sentence's effective speaker differs from the sentence before it, which
  // - once a per-sentence override exists (state.assignLine) - can happen
  // in the MIDDLE of a turn, splitting it into two runs, or make a
  // reassigned sentence merge into an adjacent run of its new speaker. A
  // per-turn ".plain-row" (the old shape) could never express a heading
  // appearing mid-turn; a 1:1 .plain-line-to-.bubble mapping, keyed on the
  // same data-line id, can.
  //
  // Headings are cheap to recreate outright every rebuild - they carry no
  // editable state (contenteditable="false") and no id worth reusing.
  // .plain-line elements ARE reused, keyed by data-line, both so an
  // in-progress edit's caret survives a rebuild triggered by something else
  // on the page, and so a line currently focused is never overwritten (the
  // same "never rewrite what the caret is in" rule runSearch() already
  // follows for the card). Reusing an already-attached element via
  // container.appendChild() moves it to its new position without losing
  // focus or listeners, which is what lets one forward pass over every
  // sentence, in order, produce the whole panel's final DOM order.
  function rebuildPlain(section) {
    if (!section) { return; }
    var panel = section.querySelector('.plain');
    if (!panel) { return; }
    var container = panel.querySelector('.plain-text');
    if (!container) { return; }

    var tsBox = panel.querySelector('.opt-ts');
    var spkBox = panel.querySelector('.opt-spk');
    var withTs = tsBox ? tsBox.checked : false;
    var withSpk = spkBox ? spkBox.checked : false;

    // Headings carry no identity worth preserving - drop every one up
    // front and let the walk below recreate exactly the set (and order)
    // that belongs.
    Array.prototype.slice.call(container.querySelectorAll('.plain-heading')).forEach(function (h) {
      h.remove();
    });

    // Existing .plain-line elements, keyed by data-line, so a line that
    // still exists after this rebuild is MOVED (via appendChild) and
    // updated in place rather than thrown away and recreated - the thing
    // that preserves a reader's caret if they are mid-edit somewhere else
    // in the panel.
    var existingLines = {};
    Array.prototype.slice.call(container.querySelectorAll('.plain-line')).forEach(function (lineEl) {
      existingLines[lineEl.dataset.line] = lineEl;
    });

    var seen = {};
    // A per-document running count, 1-based, exactly like render_html's own
    // sentence_number in core/formatting/document.py - it has to walk every
    // sentence in the same document order that renderer does, incrementing
    // for every sentence regardless of whether it ends up with visible
    // text, or a card's bubble numbers and this panel's numbers would drift
    // apart the first time a sentence's text is edited down to nothing.
    var sentenceNumber = 1;
    // The previous line's own effective speaker name - override-aware,
    // recomputed on every rebuild rather than fixed at render time: a
    // per-bubble override (state.assignLine) can change a sentence's
    // effective speaker client-side, which can open or close a run
    // boundary that did not exist at the initial server render. Tracked as
    // '' (never null) when the current line has no speaker at all, so a
    // no-speaker line and a first-ever line are never mistaken for
    // matching some earlier named run.
    var previousName = '';

    section.querySelectorAll('.turn').forEach(function (turn) {
      var cardBody = turn.querySelector('.body');
      var hasSpeaker = typeof turn.dataset.speaker !== 'undefined';
      var clusterName = hasSpeaker ? clusterSpeakerName(turn) : '';

      // Walked from the bubbles themselves, not readParagraphs(), so each
      // sentence's own effective name can be read off the SAME element the
      // text and timing come from. Falls back to readParagraphs()'s flatter
      // shape - no per-sentence name or real timing, since there is no
      // .bubble to read either off - for the one case writeParagraphs()
      // itself already documents: a body with no .bubble wrapper at all.
      var bubbleEls = Array.prototype.slice.call(cardBody.querySelectorAll('.bubble'));
      var entries;
      if (bubbleEls.length) {
        entries = bubbleEls.map(function (b) {
          var p = b.querySelector('p');
          return {
            lineId: b.dataset.line,
            text: p ? p.textContent : '',
            start: parseFloat(b.dataset.start),
            end: parseFloat(b.dataset.end),
            name: hasSpeaker ? bubbleSpeakerName(b, clusterName) : '',
          };
        });
      } else {
        // No timing to read per sentence - falls back to the turn's own
        // start, the same fallback Turn.sentences() (turns.py) uses
        // server-side when a turn carries no word timings.
        // formatSentenceRange() imposes its own one-second floor on the
        // end, so this still renders a valid, if approximate, range.
        var fallbackStart = parseFloat(turn.dataset.start) || 0;
        entries = readParagraphs(cardBody).map(function (text, idx) {
          return {
            lineId: turn.dataset.turn + '-' + idx,
            text: text,
            start: fallbackStart,
            end: fallbackStart,
            name: hasSpeaker ? clusterName : '',
          };
        });
      }

      entries.forEach(function (entry) {
        var number = sentenceNumber++;
        // Computed unconditionally, every sentence, regardless of withSpk -
        // the run boundary itself does not depend on whether the checkbox
        // happens to be checked right now, only the DISPLAY of the heading
        // does (see below). Tracking it unconditionally is what lets
        // re-checking the box later reproduce the same run boundaries a
        // fresh server render would have shown.
        var showHeading = hasSpeaker && entry.name !== previousName;
        previousName = entry.name;

        var trimmed = entry.text.replace(/^\s+|\s+$/g, '');
        if (!trimmed) {
          // The sentence's own text was edited down to nothing without its
          // bubble disappearing outright - its line has to go too, not
          // just skip being refreshed. Left out of `seen`, so the cleanup
          // pass below removes it if it still exists from a previous
          // rebuild.
          return;
        }
        seen[entry.lineId] = true;

        if (showHeading && withSpk) {
          var heading = el('div', 'plain-heading', { contenteditable: 'false' });
          // Trailing colon, matching _render_plain_html() in
          // core/formatting/document.py. These two MUST agree exactly: the
          // server renders the panel and this rebuilds it, so any
          // difference shows up as the panel rewriting itself the first
          // time the reader toggles a checkbox.
          heading.textContent = entry.name + ':';
          container.appendChild(heading);
        }

        var lineEl = existingLines[entry.lineId];
        if (!lineEl) {
          lineEl = el('div', 'plain-line');
          lineEl.dataset.line = entry.lineId;
          var bodyEl = el('span', 'plain-body', {
            contenteditable: 'true',
            role: 'textbox',
            'aria-label': t('turn_text', 'Turn text'),
          });
          lineEl.appendChild(bodyEl);
          existingLines[entry.lineId] = lineEl;
        }
        container.appendChild(lineEl);

        var bodyEl2 = lineEl.querySelector('.plain-body');
        var text = lineLeadIn(number, entry.start, entry.end, withTs) + entry.text;
        if (document.activeElement !== bodyEl2 && bodyEl2.textContent !== text) {
          bodyEl2.textContent = text;
        }
      });
    });

    Object.keys(existingLines).forEach(function (lineId) {
      if (!seen[lineId]) { existingLines[lineId].remove(); }
    });
  }

  // "Copy all" reassembles from the headings and lines themselves rather
  // than reading container.textContent, which would run every sentence's
  // text together with no separator at all. Walking the panel's own
  // children and joining explicitly also keeps this in step with whatever
  // the reader has actually typed into a .plain-body, since it reads the
  // live elements, not a cached string.
  // U+200F RIGHT-TO-LEFT MARK. An invisible strong-RTL character, used only
  // when text LEAVES the page. gui/i18n.py keeps one for the same purpose,
  // on GUI lines that open with a Latin filename.
  var PLAIN_RLM = '‏';

  // Anchors one copied line so a receiving app lays it out right-to-left.
  //
  // Inside the browser this is unnecessary: the document is dir="rtl" and
  // the paragraph direction is settled. Once copied out it is not. Apps that
  // guess a paragraph's direction use its FIRST STRONG character, and every
  // line now opens with the sentence number - an LTR run inside an isolate -
  // so Word, Notepad and most chat apps saw a left-to-right line and
  // left-aligned the whole thing, Hebrew and all. An RLM makes the first
  // strong character right-to-left, which is what the reader means, and
  // displays nothing.
  //
  // Applied at the copy boundary rather than baked into the rendered text on
  // purpose: .plain-body is contenteditable, and anything that lives in it
  // has to be stripped back off before an edit reaches a card (see
  // stripLineNumber). A character that exists only in the clipboard cannot
  // be typed over, half-deleted, or persisted into someone's transcript.
  function anchorRtl(line) {
    return line ? PLAIN_RLM + line : line;
  }

  // Walks the panel's own children (a flat sequence of .plain-heading and
  // .plain-line elements - see rebuildPlain()) in document order, grouping
  // each heading together with the lines that follow it into one copied
  // block, separated by a blank line from the next. With .opt-spk off there
  // are no headings at all, so every line joins one continuous block - there
  // is no other cue left in the DOM for where a reader would expect a break.
  function plainPanelText(panel) {
    var blocks = [];
    var current = [];
    function flush() {
      if (current.length) { blocks.push(current.join('\n')); }
      current = [];
    }
    Array.prototype.forEach.call(panel.querySelectorAll('.plain-heading, .plain-line'), function (node) {
      if (node.classList.contains('plain-heading')) {
        var heading = node.textContent.replace(/^\s+|\s+$/g, '');
        if (!heading) { return; }
        flush();
        current.push(anchorRtl(heading));
        return;
      }
      var bodyEl = node.querySelector('.plain-body');
      var body = bodyEl ? bodyEl.textContent.replace(/^\s+|\s+$/g, '') : '';
      if (!body) { return; }
      current.push(anchorRtl(body));
    });
    flush();
    return blocks.join('\n\n');
  }

  function bindPlain() {
    document.querySelectorAll('.plain').forEach(function (panel) {
      var section = panel.closest('.source');

      panel.querySelectorAll('.opt-ts, .opt-spk').forEach(function (box) {
        box.addEventListener('change', function () {
          var ts = panel.querySelector('.opt-ts');
          var spk = panel.querySelector('.opt-spk');
          state.opts[section.dataset.file] = {
            ts: ts ? ts.checked : false,
            spk: spk ? spk.checked : false
          };
          rebuildPlain(section);
          save();
        });
      });

      panel.querySelector('.copy-all').addEventListener('click', function (e) {
        copy(plainPanelText(panel), e.currentTarget);
      });

      // Delegated (lines are created and destroyed by rebuildPlain(), not
      // fixed at render time) - editing a line writes straight back into
      // its matching bubble's <p> by data-line, then re-derives that
      // bubble's whole turn's saved paragraph array from every <p> still in
      // the card (readParagraphs()), since state.turns is keyed per turn,
      // not per sentence. Because this handler never calls rebuildPlain()
      // for the line it just wrote, and rebuildPlain() skips whichever line
      // currently has focus (see above), an edit here cannot circle back
      // and overwrite its own caret - the other half of the loop that guard
      // exists to break.
      var container = panel.querySelector('.plain-text');
      container.addEventListener('input', function (e) {
        var bodyEl = e.target.closest ? e.target.closest('.plain-body') : null;
        if (!bodyEl) { return; }
        var lineEl = bodyEl.closest('.plain-line');
        var lineId = lineEl.dataset.line;
        var bubble = document.querySelector('.bubble[data-line="' + lineId + '"]');
        if (!bubble) { return; }
        var turn = bubble.closest('.turn');
        if (!turn) { return; }

        // Every .plain-body starts with the same "{LRI}{n}{PDI} " lead-in
        // _render_plain_line_html() renders (see the comment on
        // stripLineNumber() above) - writing the raw textContent back would
        // capture that number (and, with timestamps on, the bracketed
        // range) as part of the sentence, and it would be baked into the
        // card permanently the moment writeParagraphs() ran.
        var text = stripLineNumber(bodyEl.textContent);
        var p = bubble.querySelector('p');
        if (p) { p.textContent = text; }

        var cardBody = turn.querySelector('.body');
        state.turns[turn.dataset.turn] = readParagraphs(cardBody);
        turn.dataset.edited = 'true';
        unflagTurn(turn);
        save();
      });

      // Same plain-text-only paste rule bindEditing() enforces on the card
      // side - markup pasted from another app must not carry fonts or
      // colours into a transcript that has no use for rich text.
      container.addEventListener('paste', function (e) {
        var bodyEl = e.target.closest ? e.target.closest('.plain-body') : null;
        if (!bodyEl) { return; }
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text');
        document.execCommand('insertText', false, text);
      });
    });

    // Per-card copy, the replacement for the old per-turn "copy this turn"
    // action - see bubblePlainText()'s own comment for why that action has
    // no cluster-header home left.
    document.querySelectorAll('.copy-line').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var bubble = btn.closest('.bubble');
        // Anchored the same way the panel's copy is: this text opens with a
        // bracketed timestamp, an LTR run, so an app guessing direction from
        // the first strong character would left-align the Hebrew after it.
        copy(anchorRtl(bubblePlainText(bubble, true, true)), btn);
      });
    });
  }

  function copy(text, btn) {
    // Both the async-clipboard path and the execCommand fallback funnel
    // through this one success callback, so the toast (which announces *what*
    // happened) and the button flash (which announces *which* control did it)
    // each get hooked in exactly once rather than at every call site.
    function flash() {
      btn.classList.add('copied');
      setTimeout(function () { btn.classList.remove('copied'); }, 1200);
      showToast(t('copied', 'Copied'));
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(flash).catch(function () { fallback(text, flash); });
    } else {
      fallback(text, flash);
    }
  }

  var toastTimer = null;

  function showToast(message) {
    var toast = document.getElementById('toast');
    if (!toast) { return; }
    toast.textContent = message;
    toast.hidden = false;
    // Force a synchronous layout before adding .show, so the browser commits
    // the pre-show (opacity: 0) state as a real paint before the transition
    // target changes - without this read, clearing [hidden] and adding
    // .show in the same tick can coalesce into one style recalculation and
    // the transition never has a "from" to animate out of. This used to be
    // a requestAnimationFrame callback instead, which is the textbook fix -
    // and the wrong one here: rAF is throttled to not fire at all for a
    // backgrounded tab, which left the toast sitting at opacity: 0 forever
    // whenever the reader had switched away. A synchronous layout read has
    // no such dependency on the tab being visible.
    void toast.offsetWidth;
    toast.classList.add('show');

    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('show');
      setTimeout(function () { toast.hidden = true; }, 200);
    }, 3000);
  }

  function fallback(text, done) {
    // The async clipboard API is unavailable on some file:// setups; fall back
    // to a hidden selection rather than failing silently.
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('aria-hidden', 'true');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* nothing left to try */ }
    document.body.removeChild(ta);
  }
