  // ------------------------------------------------------------- plain text

  // The card's own pill stays bare ("0:00 - 0:32"): a click target reads its
  // own shape as the label. The plain-text panel gets copied out of the
  // browser into apps with no bidi engine of their own, so it needs the
  // stronger visual cue of brackets - and, per the LRI/PDI comment block in
  // core/formatting.py, the brackets have to sit *inside* the isolate along
  // with the range, not outside it: they are mirrored characters exactly
  // like the hyphen is a neutral, so a bracket pasted outside the isolate
  // could reorder the same way the old un-isolated timestamps did.
  // PLAIN_LRI/PLAIN_PDI themselves live in the shared preamble fragment now
  // - the guided tour's own step counter needs the same pair.

  function bracketedRange(ts) {
    // ts.textContent already carries format_range()'s own LRI/PDI pair
    // (rendered by formatting.py); stripped here and reapplied around the
    // bracketed form rather than nested, so the plain-text panel still has
    // exactly one isolate pair per range, per the module docstring. Used by
    // bubblePlainText() below, reading a bubble's own rendered .ts range
    // text directly - a different thing from the per-line range
    // rebuildPlain() builds for each sentence (see numberedLines() below),
    // which has no rendered .ts to read from when a card is being rebuilt
    // from a fresh paragraph array rather than copied from an existing one.
    var bare = ts.textContent.trim().replace(/[⁦⁩]/g, '');
    return PLAIN_LRI + '[' + bare + ']' + PLAIN_PDI;
  }

  // Whole-second m:ss / h:mm:ss formatting, mirroring format_mmss()/
  // format_hhmmss() in core/formatting/timecode.py closely enough that
  // formatSentenceRange() below produces byte-identical text to
  // _render_plain_row_html()'s server render. Kept as two small functions
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

  // A sentence's own "M:SS - M:SS" range, un-isolated (numberedLines()
  // below wraps it, together with the number and the dot, in one LRI/PDI
  // pair - see the module docstring on why one isolate, not two). Mirrors
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

  // _render_plain_row_html() (core/formatting/document.py) leads every line
  // of a row's .plain-body with "{LRI}{n}{PDI}. " - or, with timestamps on,
  // "{LRI}{n}{PDI}. {LRI}[{range}]{PDI} " - the number and the range each
  // sit in their OWN isolate, with the dot and the space between them
  // OUTSIDE both. See the docstring on _render_plain_row_html() (Python
  // side) for why: a single isolate around the whole lead-in put the dot to
  // the right of the digit in RTL text - the wrong side, since the dot has
  // to separate the number from what follows it, which reads to the
  // number's LEFT in Hebrew. rebuildPlain() below has to reproduce this
  // same two-isolate lead-in when it regenerates a row from a card's own
  // text (see numberedLines()), and the panel's own input handler has to
  // strip it back off before that text is ever written back into a
  // bubble's <p> - otherwise the lead-in stops being a display artifact and
  // becomes part of the sentence, permanently, the next time this row is
  // edited. The range's own isolate is matched as an OPTIONAL group (it is
  // simply absent with timestamps off), so this one regex strips the
  // lead-in whether or not a range is present.
  var LINE_NUMBER_RE = new RegExp(
    '^' + PLAIN_LRI + '\\d+' + PLAIN_PDI + '\\. '
    + '(?:' + PLAIN_LRI + '\\[[^' + PLAIN_PDI + ']*\\]' + PLAIN_PDI + ' )?'
  );

  function stripLineNumber(line) {
    return line.replace(LINE_NUMBER_RE, '');
  }

  // A per-line speaker tag - "{LRI}[Name]{PDI} " - marking the one sentence
  // in a turn that disagrees with the row's own prefix (see
  // rowSpeakerName()'s docstring for why a row can only ever show ONE name
  // in its prefix, and what "disagrees" means there). Bracketed inside the
  // same LRI/PDI isolate bracketedRange() already uses for the timestamp,
  // for the same reason: a bare "[" is a mirrored character that can
  // reorder inside RTL text once it leaves the browser's own bidi engine
  // (see the module docstring above and timecode.py's own).
  function bracketedName(name) {
    return PLAIN_LRI + '[' + name + ']' + PLAIN_PDI;
  }

  // The inverse half of bracketedName(): strips a leading tag back off
  // before a plain-panel edit is written back into a bubble's <p>, the same
  // "display artifact, not real text" treatment stripLineNumber() already
  // gives the line number it always precedes (see numberedLines() below for
  // why the tag always comes right after the number, never before it).
  var LINE_TAG_RE = new RegExp('^' + PLAIN_LRI + '\\[[^\\]]*\\]' + PLAIN_PDI + ' ?');

  function stripLineOverrideTag(line) {
    return line.replace(LINE_TAG_RE, '');
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

  // What name a TURN's plain-text row shows in its own "{Name}:" prefix,
  // now that a bubble can carry a per-sentence override (the "no feature
  // loss" checklist's "Reassign speaker" row - see reassignLine() in
  // js/24-speakers-menus.js). A row is per-turn, not per-line, and its
  // prefix has exactly one slot for "who" - it was never rebuilt to hold a
  // set of names - so this is the one place that decision gets made:
  //
  //   - If every bubble in the turn currently agrees on a name (the
  //     ordinary case with no override at all, AND the less-ordinary case
  //     where every sentence has been overridden to the SAME other
  //     speaker), that agreed name is simply correct and is shown here.
  //   - If they genuinely disagree, the prefix falls back to the cluster's
  //     own name - the row's default, unsurprising meaning - and each
  //     disagreeing sentence is tagged individually instead (see
  //     bracketedName() above and its callers below), the same way the
  //     card itself shows the cluster's chip once at the top and only a
  //     disagreeing bubble grows a chip of its own.
  //
  // This is why a bubble is only ever tagged when its own name differs from
  // whatever rowSpeakerName() decided, rather than whenever it merely
  // carries an override: an override that everyone in the turn shares is
  // not a disagreement, so the row's own prefix already says all of it.
  function rowSpeakerName(turn, clusterName) {
    var names = [];
    turn.querySelectorAll('.body .bubble').forEach(function (bubble) {
      names.push(bubbleSpeakerName(bubble, clusterName));
    });
    for (var i = 1; i < names.length; i++) {
      if (names[i] !== names[0]) { return clusterName; }
    }
    return names.length ? names[0] : clusterName;
  }

  // The inverse of stripLineNumber()/stripLineOverrideTag(): lays the same
  // "{LRI}{n}.{PDI} " (or, with withTs, "{LRI}{n}. [{range}]{PDI} ") lead-in
  // _render_plain_row_html() (core/formatting/document.py) uses over one
  // turn's paragraph array, numbered from `first`, with an optional
  // bracketed name tag (see bracketedName()) right after the lead-in and
  // before the sentence text - so a row rebuilt client-side (a reader typed
  // into the card, or an override was just set, or the .opt-ts toggle
  // changed) shows the same text a fresh server render would, plus
  // whichever per-line tags rowSpeakerName()'s decision calls for.
  // `tags[idx]` is a name string to tag that line with, or falsy for an
  // ordinary, untagged line. `times[idx]` is that line's own
  // {start, end} - required whenever withTs is true, since the range is
  // per-sentence, not per-row (see formatSentenceRange() above).
  function numberedLines(paragraphs, first, tags, times, withTs) {
    return paragraphs.map(function (text, idx) {
      var number = first + idx;
      // Two isolates, dot outside both - see LINE_NUMBER_RE's own comment
      // above for why. Must stay byte-identical to _render_plain_row_html()
      // (core/formatting/document.py).
      var lead = PLAIN_LRI + number + PLAIN_PDI + '. ';
      if (withTs && times && times[idx]) {
        lead += PLAIN_LRI + '[' +
          formatSentenceRange(times[idx].start, times[idx].end) + ']' + PLAIN_PDI + ' ';
      }
      var tag = tags && tags[idx];
      if (tag) { lead += bracketedName(tag) + ' '; }
      return lead + text;
    }).join('\n');
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
  // fallback the way bubbleSpeakerName() does for the plain-panel's tags.
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

  // Builds or updates one .plain-row per turn - never a full teardown and
  // rebuild of the panel's innerHTML, which is what the single-<pre>
  // version used to do and exactly what would fight a reader mid-edit: a
  // fresh row replaces the live one under their caret every time any turn
  // anywhere in the file changes. Two guards instead: skip a row whose
  // .plain-body currently has focus (the same "never rewrite what the caret
  // is in" rule runSearch() already follows for the card), and only touch a
  // node's text when it would actually change, so an unrelated row's
  // scroll position and selection are left alone too.
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

    // A per-document running count, 1-based, exactly like render_html's own
    // sentence_number in core/formatting/document.py - it has to walk every
    // turn in the same document order that renderer does, incrementing by
    // each turn's own paragraph count regardless of whether that turn ends
    // up with a visible row, or a card's bubble numbers and this panel's
    // row numbers would drift apart the first time a turn's text is edited
    // down to nothing.
    var seen = {};
    var sentenceNumber = 1;
    // The previous row's own effective speaker name (rowName, below) -
    // override-aware, the same value _render_plain_html()'s previous_speaker
    // tracks server-side, except this has to be recomputed on every
    // rebuild rather than fixed at render time: a per-card override
    // (state.assignLine) can change a row's effective speaker client-side,
    // which can open or close a run boundary that did not exist at the
    // initial server render. See _render_plain_row_html()'s docstring.
    var previousRowName = null;
    section.querySelectorAll('.turn').forEach(function (turn) {
      var turnId = turn.dataset.turn;
      // Own name (cardBody), deliberately not `bodyEl` - a .plain-row's own
      // .plain-body span is built or looked up further down this same loop
      // body under that exact name, and reusing it here for the CARD's
      // .body would be one identifier meaning two different elements across
      // one iteration.
      var cardBody = turn.querySelector('.body');
      var hasSpeaker = typeof turn.dataset.speaker !== 'undefined';
      var clusterName = hasSpeaker ? clusterSpeakerName(turn) : '';
      var rowName = hasSpeaker ? rowSpeakerName(turn, clusterName) : clusterName;

      // Walked from the bubbles themselves, not readParagraphs(), so each
      // paragraph's own per-line tag (see numberedLines()/rowSpeakerName())
      // can be read off the SAME element the text came from. Falls back to
      // readParagraphs()'s flatter shape - no tags, since there is nothing
      // to read one off - for the one case writeParagraphs() itself already
      // documents: a body with no .bubble wrapper at all.
      var bubbleEls = Array.prototype.slice.call(cardBody.querySelectorAll('.bubble'));
      var paragraphs, tags, times;
      if (bubbleEls.length) {
        paragraphs = bubbleEls.map(function (b) {
          var p = b.querySelector('p');
          return p ? p.textContent : '';
        });
        tags = bubbleEls.map(function (b) {
          var name = bubbleSpeakerName(b, clusterName);
          return name !== rowName ? name : null;
        });
        times = bubbleEls.map(function (b) {
          return { start: parseFloat(b.dataset.start), end: parseFloat(b.dataset.end) };
        });
      } else {
        // No .bubble wrapper at all (see writeParagraphs()'s own comment on
        // this case) - there is no per-sentence span to read a range from
        // at all any more (there is no cluster-header .ts either, now that
        // the header is gone - see _render_turn_html()'s docstring), so
        // every line falls back to the turn's own start, the same fallback
        // Turn.sentences() (turns.py) uses server-side when a turn carries
        // no word timings. formatSentenceRange() imposes its own one-second
        // floor on the end, so this still renders a valid, if approximate,
        // range rather than a degenerate one.
        paragraphs = readParagraphs(cardBody);
        tags = paragraphs.map(function () { return null; });
        var fallbackStart = parseFloat(turn.dataset.start) || 0;
        times = paragraphs.map(function () {
          return { start: fallbackStart, end: fallbackStart };
        });
      }

      // Computed unconditionally, every turn, regardless of withSpk - the
      // run boundary itself does not depend on whether the checkbox happens
      // to be checked right now, only the DISPLAY of the heading does (see
      // below). Tracking it unconditionally is what lets re-checking the
      // box later reproduce the same run boundaries a fresh server render
      // would have shown.
      var showHeading = hasSpeaker && rowName !== previousRowName;
      previousRowName = rowName;

      var trimmed = paragraphs.join('\n').replace(/^\s+|\s+$/g, '');
      var row = container.querySelector('.plain-row[data-turn="' + turnId + '"]');

      if (!trimmed) {
        if (row) { row.remove(); }
        sentenceNumber += paragraphs.length;
        return;
      }
      var text = numberedLines(paragraphs, sentenceNumber, tags, times, withTs);
      sentenceNumber += paragraphs.length;
      seen[turnId] = true;

      if (!row) {
        row = el('div', 'plain-row');
        row.dataset.turn = turnId;

        var bodyEl = el('span', 'plain-body', {
          contenteditable: 'true',
          role: 'textbox',
          'aria-multiline': 'true',
          'aria-label': t('turn_text', 'Turn text'),
        });
        row.appendChild(bodyEl);

        container.appendChild(row);
      }

      // The heading is its own block-level line above .plain-body, not an
      // inline prefix - see _render_plain_row_html()'s docstring for why -
      // present only when this row starts a new run (showHeading) AND the
      // reader has the speaker-names toggle on.
      var headingEl = row.querySelector('.plain-heading');
      if (showHeading && withSpk) {
        if (!headingEl) {
          headingEl = el('div', 'plain-heading', { contenteditable: 'false' });
          row.insertBefore(headingEl, row.firstChild);
        }
        if (headingEl.textContent !== rowName) { headingEl.textContent = rowName; }
      } else if (headingEl) {
        headingEl.remove();
      }

      var bodyEl = row.querySelector('.plain-body');
      if (document.activeElement !== bodyEl && bodyEl.textContent !== text) {
        bodyEl.textContent = text;
      }
    });

    // A turn's body can go empty (every sentence deleted) without the turn
    // itself disappearing - its row has to go too, not just skip being
    // refreshed above.
    container.querySelectorAll('.plain-row').forEach(function (row) {
      if (!seen[row.dataset.turn]) { row.remove(); }
    });
  }

  // "Copy all" reassembles from the rows themselves rather than reading
  // container.textContent: the DOM has no separator between one row and the
  // next (each is just a sibling <div>), so a raw textContent scrape would
  // run every turn's text together with no blank line between them. Walking
  // the rows and joining explicitly is also what keeps this in step with
  // whatever the reader has actually typed into a .plain-body, since it
  // reads the live element, not a cached string.
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

  function plainPanelText(panel) {
    var blocks = [];
    panel.querySelectorAll('.plain-row').forEach(function (row) {
      var headingEl = row.querySelector('.plain-heading');
      var bodyEl = row.querySelector('.plain-body');
      var body = bodyEl ? bodyEl.textContent.replace(/^\s+|\s+$/g, '') : '';
      if (!body) { return; }
      var heading = headingEl ? headingEl.textContent.replace(/^\s+|\s+$/g, '') : '';
      var lines = (heading ? heading + '\n' + body : body).split('\n');
      blocks.push(lines.map(anchorRtl).join('\n'));
    });
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

      // Delegated (rows are created and destroyed by rebuildPlain(), not
      // fixed at render time) - editing a row writes straight back into the
      // card's own .body via writeParagraphs(), the same paragraph-array
      // shape readParagraphs() produces from a card, so nothing here ever
      // has to parse the plain-text panel's own markup back apart. Because
      // this handler never calls rebuildPlain() for the row it just wrote,
      // and rebuildPlain() skips whichever row currently has focus (see
      // above), an edit here cannot circle back and overwrite its own
      // caret - the other half of the loop that guard exists to break.
      var container = panel.querySelector('.plain-text');
      container.addEventListener('input', function (e) {
        var bodyEl = e.target.closest ? e.target.closest('.plain-body') : null;
        if (!bodyEl) { return; }
        var row = bodyEl.closest('.plain-row');
        var turn = document.querySelector('.turn[data-turn="' + row.dataset.turn + '"]');
        if (!turn) { return; }

        // Every line of a row's .plain-body starts with the same
        // "{LRI}{n}{PDI} " lead-in _render_plain_row_html() renders (see
        // the comment on stripLineNumber() above) - splitting on '\n' alone
        // would capture that number as part of the sentence and
        // writeParagraphs() would bake it into the card permanently. A
        // disagreeing line can carry a second, optional "{LRI}[Name]{PDI} "
        // tag right after the number (see numberedLines()/bracketedName())
        // that needs stripping for exactly the same reason - otherwise
        // reassigning a sentence and then merely editing its text through
        // THIS panel would bake "[Name] " into the sentence permanently.
        var paragraphs = bodyEl.textContent.split('\n')
          .map(stripLineNumber).map(stripLineOverrideTag);
        state.turns[row.dataset.turn] = paragraphs;
        turn.dataset.edited = 'true';
        unflagTurn(turn);
        writeParagraphs(turn.querySelector('.body'), paragraphs);
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
