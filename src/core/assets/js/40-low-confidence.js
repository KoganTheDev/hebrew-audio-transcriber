
  // A turn's words are rendered from three inputs: the text in the card, the
  // reader's picks for its uncertain words (state.picks, made in the
  // click-to-fix menu - js/42-fix-menu.js), and whether highlighting is on.
  // renderTurn() is the one function that combines them, so loading, a pick,
  // the toolbar toggle and export can never disagree about what a card shows.
  //
  // DATA.low[turnId] entries are [word, probability, occurrence, suggestions,
  // original] (core/formatting/turns.py). The occurrence index disambiguates
  // a word that appears more than once in a turn with different confidences,
  // so only the uncertain one is shaded. A picked word keeps the word it
  // replaced in data-orig, so occurrences are still counted against what the
  // model wrote after the reader has changed it.

  function lowEntries(turnId) {
    var byKey = {};
    (DATA.low[turnId] || []).forEach(function (e) { byKey[e[0] + '#' + e[2]] = e; });
    return byKey;
  }

  // The card's words as {text, orig} pieces, whitespace kept as its own
  // pieces. Reads through spans this module made (.lowconf, .picked) to the
  // word each one stands for; any other element (a search <mark>) is read as
  // its text.
  function piecesOf(p) {
    var pieces = [];
    p.childNodes.forEach(function (node) {
      if (node.nodeType === 1 && node.dataset && node.dataset.orig !== undefined) {
        pieces.push({ text: node.textContent, orig: node.dataset.orig });
        return;
      }
      node.textContent.split(/(\s+)/).forEach(function (tok) {
        if (tok) { pieces.push({ text: tok, orig: /^\s+$/.test(tok) ? null : tok }); }
      });
    });
    return pieces;
  }

  // Built from DOM nodes, never an HTML string: transcript text is model- and
  // user-supplied, so splicing it into markup would re-interpret any "<" it
  // happens to contain.
  function wordSpan(entry, key, text) {
    var span = el('span', 'lowconf' + (entry[4] ? ' autofixed' : ''), {
      role: 'button',
      tabindex: '0',
      'aria-haspopup': 'menu',
      // A control inside an editable card: without this the click places a
      // caret in the word instead of opening its menu, and typing would edit
      // a node the next render throws away.
      contenteditable: 'false',
    });
    span.dataset.orig = key.slice(0, key.lastIndexOf('#'));
    span.dataset.occ = key.slice(key.lastIndexOf('#') + 1);
    span.title = t('confidence', 'confidence') + ' ' + entry[1].toFixed(2);
    span.textContent = text;
    return span;
  }

  function renderTurn(turn) {
    if (turn.dataset.edited === 'true') { unflagTurn(turn); return; }
    var turnId = turn.dataset.turn;
    var entries = lowEntries(turnId);
    var picks = (state.picks && state.picks[turnId]) || {};
    if (!Object.keys(entries).length && !Object.keys(picks).length) { return; }

    // Counted across the whole turn, every word, so the index lines up with
    // the one the renderer computed over the turn's full word list.
    var seen = {};
    turn.querySelectorAll('.body p').forEach(function (p) {
      var frag = document.createDocumentFragment();
      piecesOf(p).forEach(function (piece) {
        if (piece.orig === null) {
          frag.appendChild(document.createTextNode(piece.text));
          return;
        }
        var i = (seen[piece.orig] === undefined) ? 0 : seen[piece.orig] + 1;
        seen[piece.orig] = i;
        var key = piece.orig + '#' + i;
        var pick = picks[key];

        if (typeof pick === 'string') {
          var picked = el('span', 'picked');
          picked.dataset.orig = piece.orig;
          picked.textContent = pick;
          frag.appendChild(picked);
        } else if (pick === undefined && entries[key] && state.flags) {
          frag.appendChild(wordSpan(entries[key], key, piece.text));
        } else {
          frag.appendChild(document.createTextNode(piece.text));
        }
      });
      p.textContent = '';
      p.appendChild(frag);
    });
  }

  // The card has become ordinary edited text: what the model doubted no
  // longer describes it, and a pick marker no longer means anything.
  function unflagTurn(turn) {
    turn.querySelectorAll('.lowconf, .picked').forEach(function (span) {
      span.replaceWith(document.createTextNode(span.textContent));
    });
    turn.normalize();
  }

  function setFlags(on) {
    state.flags = on;
    var btn = document.getElementById('toggle-flags');
    if (btn) { btn.setAttribute('aria-pressed', String(on)); }
    document.querySelectorAll('.turn').forEach(renderTurn);
  }

  // The rendered page with every pick marker reduced to its text, for a
  // document leaving the page (export, save): the copy carries the reader's
  // choices as plain words, not as markup only this script understands.
  function stripPickMarkers(html) {
    // Any class list starting "picked": a fresh pick is also "just-picked".
    return html.replace(/<span class="picked(?: [^"]*)?"[^>]*>([^<]*)<\/span>/g, '$1');
  }
