
  // Edits are stored as an array of plain paragraph strings, never as raw
  // innerHTML: markup pasted from another app would otherwise be persisted
  // and re-injected verbatim on the next load.
  //
  // A card's body is one <div class="bubble"> per sentence, each carrying a
  // .ts with contenteditable="false" (see _render_bubble_html() in
  // core/formatting/document.py). Reading body.children would treat those
  // wrappers as the paragraphs and bake the timestamp into the saved text;
  // querySelectorAll('p') skips the .ts sibling because it is not a <p>, and
  // still catches a stray <p> that ended up outside a bubble.
  function readParagraphs(body) {
    var paras = Array.prototype.slice.call(body.querySelectorAll('p'));
    if (!paras.length) { return [body.textContent]; }
    return paras.map(function (p) { return p.textContent; });
  }

  // Writes text back into the existing bubbles rather than rebuilding the
  // body from bare <p> elements: the wrapper, data-line, data-start/data-end
  // and .ts are what make per-bubble playback and the numbered plain-text
  // panel work, and none of it survives a throw-away-and-recreate write.
  //
  // The paragraph count can differ from the bubble count - a reader can
  // delete a sentence, merge two lines, or paste in a line break - and there
  // is no timing to invent for a sentence the transcript never had:
  //   - fewer paragraphs than bubbles: the trailing bubbles are removed
  //     rather than left empty with stale start/end times.
  //   - more paragraphs than bubbles: the overflow is space-joined into the
  //     last bubble rather than given fabricated timestamps.
  function writeParagraphs(body, paragraphs) {
    var bubbles = Array.prototype.slice.call(body.children).filter(function (node) {
      return node.classList && node.classList.contains('bubble');
    });

    if (!bubbles.length) {
      // No bubble wrapper to preserve, so fall back to a flat run of <p> and
      // still get the text written.
      body.textContent = '';
      paragraphs.forEach(function (text) {
        var p = document.createElement('p');
        p.textContent = text;
        body.appendChild(p);
      });
      return;
    }

    for (var i = 0; i < bubbles.length; i++) {
      var p = bubbles[i].querySelector('p');
      if (!p) { continue; }
      if (i >= paragraphs.length) {
        bubbles[i].remove();
        continue;
      }
      p.textContent = (i === bubbles.length - 1 && paragraphs.length > bubbles.length)
        ? paragraphs.slice(i).join(' ')
        : paragraphs[i];
    }
  }

  function bindEditing() {
    document.querySelectorAll('.turn').forEach(function (turn) {
      var body = turn.querySelector('.body');
      if (!body) { return; }

      body.addEventListener('input', function () {
        state.turns[turn.dataset.turn] = readParagraphs(body);
        turn.dataset.edited = 'true';
        // Confidence shading describes what the model produced, not what the
        // user has since typed, so an edited card stops being shaded.
        unflagTurn(turn);
        rebuildPlain(turn.closest('.source'));
        save();
      });

      // Force plain-text paste so pasting from another document cannot drag
      // fonts, colours or arbitrary markup into the transcript.
      body.addEventListener('paste', function (e) {
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text');
        document.execCommand('insertText', false, text);
      });
    });
  }

  function applyEdits() {
    Object.keys(state.turns).forEach(function (id) {
      var turn = document.querySelector('.turn[data-turn="' + id + '"]');
      if (!turn) { return; }
      var saved = state.turns[id];
      writeParagraphs(turn.querySelector('.body'), Array.isArray(saved) ? saved : [String(saved)]);
      turn.dataset.edited = 'true';
    });
  }
