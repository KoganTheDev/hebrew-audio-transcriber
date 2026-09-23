
  function flagTurn(turn) {
    if (turn.dataset.edited === 'true') { return; }
    var entries = DATA.low[turn.dataset.turn];
    if (!entries || !entries.length) { return; }

    // entries are [word, probability, occurrence] - the occurrence index
    // disambiguates a word that appears more than once in the same turn with
    // different confidences, so only the uncertain one gets shaded.
    var wanted = {};
    entries.forEach(function (e) {
      wanted[e[0]] = wanted[e[0]] || {};
      wanted[e[0]][e[2]] = e[1];
    });

    var seen = {};
    turn.querySelectorAll('.body p').forEach(function (p) {
      var tokens = p.textContent.split(/(\s+)/);
      var frag = document.createDocumentFragment();

      tokens.forEach(function (tok) {
        if (!tok || /^\s+$/.test(tok)) {
          frag.appendChild(document.createTextNode(tok));
          return;
        }
        // Count every occurrence, not just wanted ones, so the index lines up
        // with the one the renderer computed over the full word list.
        var i = (seen[tok] === undefined) ? 0 : seen[tok] + 1;
        seen[tok] = i;

        var prob = wanted[tok] && wanted[tok][i];
        if (prob === undefined) {
          frag.appendChild(document.createTextNode(tok));
          return;
        }
        // Built from DOM nodes, never an HTML string: transcript text is
        // model- and user-supplied, so splicing it into markup would
        // re-interpret any "<" it happens to contain.
        var span = el('span', 'lowconf');
        span.title = t('confidence', 'confidence') + ' ' + prob.toFixed(2);
        span.textContent = tok;
        frag.appendChild(span);
      });

      p.textContent = '';
      p.appendChild(frag);
    });
  }

  function unflagTurn(turn) {
    turn.querySelectorAll('.lowconf').forEach(function (span) {
      span.replaceWith(document.createTextNode(span.textContent));
    });
    turn.normalize();
  }

  function setFlags(on) {
    state.flags = on;
    var btn = document.getElementById('toggle-flags');
    if (btn) { btn.setAttribute('aria-pressed', String(on)); }
    document.querySelectorAll('.turn').forEach(on ? flagTurn : unflagTurn);
  }
