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
    // exactly one isolate pair per range, per the module docstring.
    var bare = ts.textContent.trim().replace(/[⁦⁩]/g, '');
    return PLAIN_LRI + '[' + bare + ']' + PLAIN_PDI;
  }

  // _render_plain_row_html() (core/formatting/document.py) leads every line
  // of a row's .plain-body with "{LRI}{n}{PDI} " - the same sentence number
  // shown on the matching bubble's .line-no, so a reader can cross-reference
  // one against the other. rebuildPlain() below has to reproduce that same
  // lead-in when it regenerates a row from a card's own text (see
  // numberedLines()), and the panel's own input handler has to strip it
  // back off before that text is ever written back into a bubble's <p> -
  // otherwise the number stops being a display artifact and becomes part of
  // the sentence, permanently, the next time this row is edited.
  var LINE_NUMBER_RE = new RegExp('^' + PLAIN_LRI + '\\d+' + PLAIN_PDI + ' ?');

  function stripLineNumber(line) {
    return line.replace(LINE_NUMBER_RE, '');
  }

  // The inverse of stripLineNumber(): lays the same "{LRI}{n}{PDI} " lead-in
  // formatting.py's _render_plain_row_html() uses over one turn's paragraph
  // array, numbered from `first` - so a row rebuilt client-side (a reader
  // typed into the card, not the plain panel) shows the same numbers a
  // fresh server render would.
  function numberedLines(paragraphs, first) {
    return paragraphs.map(function (text, idx) {
      return PLAIN_LRI + (first + idx) + PLAIN_PDI + ' ' + text;
    }).join('\n');
  }

  function turnPlainText(turn, withTs, withSpk) {
    var prefix = [];
    var ts = turn.querySelector('.ts');
    var spk = turn.querySelector('.spk');
    if (withTs && ts) { prefix.push(bracketedRange(ts)); }
    if (withSpk && spk) { prefix.push(spk.textContent.trim() + ':'); }

    var lines = [];
    turn.querySelectorAll('.body p').forEach(function (p) {
      var text = p.textContent.trim();
      if (text) { lines.push(text); }
    });
    if (!lines.length) { return ''; }

    var head = prefix.join(' ');
    return head ? head + ' ' + lines.join('\n') : lines.join('\n');
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
    section.querySelectorAll('.turn').forEach(function (turn) {
      var turnId = turn.dataset.turn;
      var paragraphs = readParagraphs(turn.querySelector('.body'));
      var trimmed = paragraphs.join('\n').replace(/^\s+|\s+$/g, '');
      var row = container.querySelector('.plain-row[data-turn="' + turnId + '"]');

      if (!trimmed) {
        if (row) { row.remove(); }
        sentenceNumber += paragraphs.length;
        return;
      }
      var text = numberedLines(paragraphs, sentenceNumber);
      sentenceNumber += paragraphs.length;
      seen[turnId] = true;

      if (!row) {
        row = el('div', 'plain-row');
        row.dataset.turn = turnId;

        var prefixEl = el('span', 'plain-prefix', { contenteditable: 'false' });
        row.appendChild(prefixEl);

        var bodyEl = el('span', 'plain-body', {
          contenteditable: 'true',
          role: 'textbox',
          'aria-multiline': 'true',
          'aria-label': t('turn_text', 'Turn text'),
        });
        row.appendChild(bodyEl);

        container.appendChild(row);
      }

      var prefix = [];
      var ts = turn.querySelector('.ts');
      var spk = turn.querySelector('.spk');
      if (withTs && ts) { prefix.push(bracketedRange(ts)); }
      if (withSpk && spk) { prefix.push(spk.textContent.trim() + ':'); }
      var prefixText = prefix.length ? prefix.join(' ') + ' ' : '';

      var prefixEl = row.querySelector('.plain-prefix');
      if (prefixEl.textContent !== prefixText) { prefixEl.textContent = prefixText; }

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
  function plainPanelText(panel) {
    var blocks = [];
    panel.querySelectorAll('.plain-row').forEach(function (row) {
      var prefixEl = row.querySelector('.plain-prefix');
      var bodyEl = row.querySelector('.plain-body');
      var body = bodyEl ? bodyEl.textContent.replace(/^\s+|\s+$/g, '') : '';
      if (!body) { return; }
      var prefix = prefixEl ? prefixEl.textContent.replace(/^\s+|\s+$/g, '') : '';
      blocks.push(prefix ? prefix + ' ' + body : body);
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
        // writeParagraphs() would bake it into the card permanently.
        var paragraphs = bodyEl.textContent.split('\n').map(stripLineNumber);
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

    document.querySelectorAll('.copy-turn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var turn = btn.closest('.turn');
        copy(turnPlainText(turn, true, true), btn);
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
