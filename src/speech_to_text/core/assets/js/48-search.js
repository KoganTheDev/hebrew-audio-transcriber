  // ----------------------------------------------------------------- search

  var NIKUD = /[֑-ׇ]/g;
  var FINALS = { 'ך': 'כ', 'ם': 'מ', 'ן': 'נ',
                 'ף': 'פ', 'ץ': 'צ' };

  // Same normalisation rules the Hebrew WER metric uses: nikud is optional
  // decoration, and a final letter form is the same letter.
  function normalise(s) {
    return s.replace(NIKUD, '')
            .replace(/[ךםןףץ]/g, function (c) { return FINALS[c]; });
  }

  var matches = [];
  var matchIndex = -1;

  function clearSearch() {
    document.querySelectorAll('mark.hit').forEach(function (m) {
      m.replaceWith(document.createTextNode(m.textContent));
    });
    document.querySelectorAll('.body, .plain-text').forEach(function (n) { n.normalize(); });
    matches = [];
    matchIndex = -1;
    var count = document.getElementById('search-count');
    if (count) { count.textContent = ''; }
  }

  function runSearch(query) {
    clearSearch();
    if (!query || query.length < 2) { return; }
    var needle = normalise(query);

    document.querySelectorAll('.body p').forEach(function (p) {
      // Never rewrite the card the caret is in - it would destroy the
      // selection mid-word.
      if (p.closest('.body') === document.activeElement) { return; }

      var text = p.textContent;
      if (normalise(text).indexOf(needle) === -1) { return; }

      var frag = document.createDocumentFragment();
      var rest = text;
      var guard = 0;
      while (guard++ < 500) {
        var at = normalise(rest).indexOf(needle);
        if (at === -1) { break; }
        frag.appendChild(document.createTextNode(rest.slice(0, at)));
        var mark = el('mark', 'hit');
        mark.textContent = rest.slice(at, at + query.length);
        frag.appendChild(mark);
        rest = rest.slice(at + query.length);
      }
      frag.appendChild(document.createTextNode(rest));
      p.textContent = '';
      p.appendChild(frag);
    });

    matches = Array.prototype.slice.call(document.querySelectorAll('mark.hit'));
    matchIndex = matches.length ? 0 : -1;
    focusMatch(0);
    updateCount();
  }

  function updateCount() {
    var count = document.getElementById('search-count');
    if (!count) { return; }
    count.textContent = matches.length
      ? (matchIndex + 1) + ' / ' + matches.length
      : t('no_results', 'No results');
  }

  function focusMatch(i) {
    if (!matches.length) { return; }
    matches.forEach(function (m) { m.classList.remove('current'); });
    matchIndex = (i + matches.length) % matches.length;
    var m = matches[matchIndex];
    m.classList.add('current');
    m.scrollIntoView({ block: 'center', behavior: scrollBehavior() });
    updateCount();
  }

  // Small step-by-one API over focusMatch(), so callers outside this
  // section (bindChrome()'s next/prev buttons and its Enter/Shift+Enter
  // handler) never have to read or write `matchIndex` themselves - it used
  // to be poked directly from three different places in bindChrome(), which
  // meant "how search advances" was defined partly here and partly there.
  function nextMatch() { focusMatch(matchIndex + 1); }
  function prevMatch() { focusMatch(matchIndex - 1); }
