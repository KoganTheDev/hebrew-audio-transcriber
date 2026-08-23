  // ------------------------------------------------------------------ edits

  // Edits are stored as an array of plain paragraph strings, never as raw
  // innerHTML. Markup pasted from another app would otherwise be persisted and
  // re-injected verbatim on the next load, and a transcript has no use for
  // rich text - the plain-text panel is the whole point of the document.
  //
  // A card's body is no longer one bare <p> per paragraph - each sentence is
  // now wrapped in a <div class="bubble"> that also carries a .line-no and a
  // .ts, both contenteditable="false" (see _render_bubble_html() in
  // core/formatting/document.py). Reading body.children directly, the way
  // this used to, would pick up those .bubble wrappers as the "paragraphs"
  // and bake the number and the timestamp into the saved text. Reading every
  // <p> in the body instead - not just direct children, since a stray edit
  // could in principle leave a <p> outside a .bubble - skips the two
  // contenteditable="false" siblings entirely, because neither is a <p>.
  function readParagraphs(body) {
    var paras = Array.prototype.slice.call(body.querySelectorAll('p'));
    if (!paras.length) { return [body.textContent]; }
    return paras.map(function (p) { return p.textContent; });
  }

  // Writes paragraph text back into the existing bubbles rather than
  // rebuilding the body from bare <p> elements - a bubble's wrapper,
  // data-line, data-start/data-end, .line-no and .ts are exactly what makes
  // per-bubble playback and the numbered plain-text panel work, and none of
  // that survives a "throw the body away and re-create it" write. Only the
  // sentence text inside each bubble's <p> changes.
  //
  // The array of paragraphs can come back a different length than the
  // number of bubbles the card started with - a reader can delete a whole
  // sentence's text, or merge two lines into one, or paste in an extra line
  // break. There is no timing to invent for a sentence that did not exist in
  // the transcript, so the two directions are handled differently:
  //   - fewer paragraphs than bubbles: the trailing bubbles have nothing
  //     left to show and are removed outright, rather than left empty with
  //     stale start/end times.
  //   - more paragraphs than bubbles: there is nowhere with real timing for
  //     the overflow to live, so it is folded into the last bubble's text
  //     (space-joined) instead of fabricating a new bubble with borrowed or
  //     invented timestamps.
  function writeParagraphs(body, paragraphs) {
    var bubbles = Array.prototype.slice.call(body.children).filter(function (node) {
      return node.classList && node.classList.contains('bubble');
    });

    if (!bubbles.length) {
      // No bubble wrapper to preserve - falls back to the flat shape this
      // function used before sentence bubbles existed, so a body that
      // somehow has none (or none yet) still gets its text written.
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
