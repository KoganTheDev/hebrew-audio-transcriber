/*
 * Mockup behaviour for the transcript document.
 *
 * This is throwaway-quality code whose only job is to make the mockup feel
 * real enough to judge. The shipped version lives in
 * speech_to_text/core/assets/transcript.js and is inlined into the output.
 *
 * One deliberate simplification vs the real thing: the JSON payload here
 * carries only the words that fell below the confidence threshold, not every
 * word with its probability. Enough to show the interaction; the real
 * renderer emits the full per-word data it already has.
 */
(function () {
  'use strict';

  var DATA = JSON.parse(document.getElementById('transcript-data').textContent);
  var DOC_ID = document.documentElement.dataset.docId;
  var KEY = 'hebrew-transcript:' + DOC_ID;

  var state = { turns: {}, names: {}, flags: false, theme: null, register: null, opts: {} };
  var exported = true;
  var saveTimer = null;

  var statusEl = document.getElementById('status');

  // ---------------------------------------------------------------- storage

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { state = Object.assign(state, JSON.parse(raw)); }
    } catch (e) {
      // Private browsing or a corrupt entry. Losing restored edits is bad but
      // a page that refuses to open is worse - carry on with the defaults.
      console.warn('could not read saved edits', e);
    }
  }

  function save() {
    setStatus('saving');
    clearTimeout(saveTimer);
    // Debounced so a fast typist writes once per pause, not once per keystroke.
    saveTimer = setTimeout(function () {
      try {
        localStorage.setItem(KEY, JSON.stringify(state));
        exported = false;
        setStatus('saved');
      } catch (e) {
        setStatus('error');
      }
    }, 400);
  }

  function setStatus(kind) {
    var text = { saving: 'שומר…', saved: 'נשמר', error: 'השמירה נכשלה' }[kind];
    statusEl.textContent = text;
    statusEl.dataset.kind = kind;
  }

  // ------------------------------------------------------------------ edits

  function eachTurn(fn) { document.querySelectorAll('.turn').forEach(fn); }

  // Edits are stored as an array of plain paragraph strings, never as raw
  // innerHTML. Two reasons: markup pasted from Word or a browser would
  // otherwise be persisted and re-injected verbatim on the next load, and a
  // transcript has no use for rich text anyway - the plain-text panel is the
  // point of the document.
  function readParagraphs(body) {
    var blocks = Array.prototype.slice.call(body.children);
    if (!blocks.length) { return [body.textContent]; }
    return blocks.map(function (el) { return el.textContent; });
  }

  function writeParagraphs(body, paragraphs) {
    body.textContent = '';
    paragraphs.forEach(function (text) {
      var p = document.createElement('p');
      p.textContent = text;
      body.appendChild(p);
    });
  }

  function bindEditing() {
    eachTurn(function (turn) {
      var body = turn.querySelector('.body');

      body.addEventListener('input', function () {
        state.turns[turn.dataset.turn] = readParagraphs(body);
        turn.dataset.edited = 'true';
        // Confidence shading describes the model's output, not whatever the
        // user has since typed, so an edited card stops being shaded.
        unflagTurn(turn);
        rebuildPlain(turn.closest('.source'));
        save();
      });

      // Force plain-text paste, so pasting from another document cannot drag
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
      // Tolerate entries written by an older build that stored a raw string.
      writeParagraphs(turn.querySelector('.body'), Array.isArray(saved) ? saved : [String(saved)]);
      turn.dataset.edited = 'true';
    });
  }

  // --------------------------------------------------------------- speakers

  function speakerFallback(index) { return 'דובר ' + (Number(index) + 1); }

  function applyNames(fileIndex) {
    var names = state.names[fileIndex] || {};
    var section = document.querySelector('.source[data-file="' + fileIndex + '"]');
    if (!section) { return; }

    section.querySelectorAll('.spk').forEach(function (el) {
      var i = el.dataset.speaker;
      el.textContent = (names[i] && names[i].trim()) || speakerFallback(i);
    });
    section.querySelectorAll('.speaker-name').forEach(function (input) {
      var i = input.closest('.speaker-row').dataset.speaker;
      if (document.activeElement !== input) { input.value = names[i] || ''; }
    });
    rebuildPlain(section);
  }

  function bindSpeakers() {
    document.querySelectorAll('.speakers').forEach(function (strip) {
      var fileIndex = strip.dataset.file;

      strip.querySelectorAll('.speaker-name').forEach(function (input) {
        input.addEventListener('input', function () {
          var i = input.closest('.speaker-row').dataset.speaker;
          state.names[fileIndex] = state.names[fileIndex] || {};
          state.names[fileIndex][i] = input.value;
          applyNames(fileIndex);
          save();
        });
      });

      strip.querySelector('.apply-all').addEventListener('click', function () {
        var source = state.names[fileIndex] || {};
        document.querySelectorAll('.speakers').forEach(function (other) {
          var target = other.dataset.file;
          if (target === fileIndex) { return; }
          state.names[target] = state.names[target] || {};
          // Only fill speakers that actually exist in the other file, so a
          // three-speaker recording never invents a third name in a
          // two-speaker one.
          other.querySelectorAll('.speaker-row').forEach(function (row) {
            var i = row.dataset.speaker;
            if (source[i]) { state.names[target][i] = source[i]; }
          });
          applyNames(target);
        });
        save();
      });
    });
  }

  // ------------------------------------------------------------- plain text

  function turnPlainText(turn, withTs, withSpk) {
    var prefix = [];
    if (withTs) { prefix.push(turn.querySelector('.ts').textContent.trim()); }
    if (withSpk) { prefix.push(turn.querySelector('.spk').textContent.trim() + ':'); }

    var lines = [];
    turn.querySelectorAll('.body p').forEach(function (p) {
      var text = p.textContent.trim();
      if (text) { lines.push(text); }
    });
    if (!lines.length) { return ''; }

    var head = prefix.join(' ');
    return head ? head + ' ' + lines.join('\n') : lines.join('\n');
  }

  function rebuildPlain(section) {
    if (!section) { return; }
    var panel = section.querySelector('.plain');
    var withTs = panel.querySelector('.opt-ts').checked;
    var withSpk = panel.querySelector('.opt-spk').checked;

    var blocks = [];
    section.querySelectorAll('.turn').forEach(function (turn) {
      var text = turnPlainText(turn, withTs, withSpk);
      if (text) { blocks.push(text); }
    });
    panel.querySelector('.plain-text').textContent = blocks.join('\n\n');
  }

  function bindPlain() {
    document.querySelectorAll('.plain').forEach(function (panel) {
      var section = panel.closest('.source');

      panel.querySelectorAll('.opt-ts, .opt-spk').forEach(function (box) {
        box.addEventListener('change', function () {
          state.opts[section.dataset.file] = {
            ts: panel.querySelector('.opt-ts').checked,
            spk: panel.querySelector('.opt-spk').checked
          };
          rebuildPlain(section);
          save();
        });
      });

      panel.querySelector('.copy-all').addEventListener('click', function (e) {
        copy(panel.querySelector('.plain-text').textContent, e.currentTarget);
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
    navigator.clipboard.writeText(text).then(function () {
      btn.classList.add('copied');
      setTimeout(function () { btn.classList.remove('copied'); }, 1200);
    }).catch(function () {
      // clipboard API is blocked on some file:// setups - fall back to a
      // selection the user can press Ctrl+C on rather than failing silently.
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) { /* nothing else to try */ }
      document.body.removeChild(ta);
    });
  }

  // ------------------------------------------------- low-confidence shading

  function flagTurn(turn) {
    if (turn.dataset.edited === 'true') { return; }
    var words = DATA.low[turn.dataset.turn];
    if (!words) { return; }

    // Built from DOM nodes rather than an HTML string: the transcript text is
    // user- and model-supplied, so splicing it into markup would re-interpret
    // any "<" it happens to contain.
    turn.querySelectorAll('.body p').forEach(function (p) {
      var frag = document.createDocumentFragment();
      var rest = p.textContent;
      var guard = 0;

      while (guard++ < 500) {
        var best = -1, bestWord = null, bestProb = 0;
        words.forEach(function (pair) {
          var at = rest.indexOf(pair[0]);
          if (at !== -1 && (best === -1 || at < best)) {
            best = at; bestWord = pair[0]; bestProb = pair[1];
          }
        });
        if (best === -1) { break; }

        frag.appendChild(document.createTextNode(rest.slice(0, best)));
        var span = document.createElement('span');
        span.className = 'lowconf';
        span.title = 'ביטחון ' + bestProb.toFixed(2);
        span.textContent = bestWord;
        frag.appendChild(span);
        rest = rest.slice(best + bestWord.length);
      }

      frag.appendChild(document.createTextNode(rest));
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
    btn.setAttribute('aria-pressed', String(on));
    eachTurn(on ? flagTurn : unflagTurn);
  }

  // ----------------------------------------------------------------- search

  var NIKUD = /[֑-ׇ]/g;
  var FINALS = { 'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ' };

  function normalise(s) {
    return s.replace(NIKUD, '').replace(/[ךםןףץ]/g, function (c) { return FINALS[c]; });
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
    document.getElementById('search-count').textContent = '';
  }

  function runSearch(query) {
    clearSearch();
    if (!query || query.length < 2) { return; }
    var needle = normalise(query);

    document.querySelectorAll('.body p').forEach(function (p) {
      // Never rewrite the card the caret is currently in - it would destroy
      // the selection mid-word.
      if (p.closest('.body') === document.activeElement) { return; }

      var text = p.textContent;
      if (normalise(text).indexOf(needle) === -1) { return; }

      var frag = document.createDocumentFragment();
      var rest = text;
      var guard = 0;
      while (guard++ < 200) {
        var at = normalise(rest).indexOf(needle);
        if (at === -1) { break; }
        frag.appendChild(document.createTextNode(rest.slice(0, at)));
        var mark = document.createElement('mark');
        mark.className = 'hit';
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
    var el = document.getElementById('search-count');
    el.textContent = matches.length ? (matchIndex + 1) + ' / ' + matches.length : 'אין תוצאות';
  }

  function focusMatch(i) {
    if (!matches.length) { return; }
    matches.forEach(function (m) { m.classList.remove('current'); });
    matchIndex = (i + matches.length) % matches.length;
    var m = matches[matchIndex];
    m.classList.add('current');
    m.scrollIntoView({ block: 'center', behavior: 'smooth' });
    updateCount();
  }

  // ----------------------------------------------------------------- export

  function exportCopy() {
    clearSearch();
    var wasFlagged = state.flags;
    if (wasFlagged) { setFlags(false); }

    var html = '<!doctype html>\n' + document.documentElement.outerHTML;
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (document.title || 'transcript') + ' (edited).html';
    a.click();
    URL.revokeObjectURL(a.href);

    if (wasFlagged) { setFlags(true); }
    exported = true;
  }

  // ------------------------------------------------------------------ audio

  function bindAudio() {
    var audio = document.getElementById('audio');
    var player = document.getElementById('player');
    var fileEl = document.getElementById('player-file');
    var timeEl = document.getElementById('player-time');
    var noteEl = document.getElementById('player-note');
    var toggle = document.getElementById('player-toggle');
    var current = null;

    function fmt(s) {
      var m = Math.floor(s / 60), r = Math.floor(s % 60);
      return m + ':' + (r < 10 ? '0' : '') + r;
    }

    document.querySelectorAll('.ts').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var section = btn.closest('.source');
        var file = section.dataset.audio;
        player.hidden = false;
        fileEl.textContent = file;

        if (current !== file) {
          current = file;
          audio.src = encodeURIComponent(file);
        }
        audio.currentTime = Number(btn.dataset.start);
        audio.play().catch(function () { /* handled by the error listener */ });
      });
    });

    audio.addEventListener('error', function () {
      // In the shipped version the player hides itself here, because a
      // missing or unplayable file means the feature simply is not available.
      // The mockup keeps it on screen so the design can still be reviewed.
      noteEl.textContent = 'מוקאפ: אין קובץ שמע לצד הדף';
      player.dataset.disabled = 'true';
    });

    audio.addEventListener('timeupdate', function () {
      timeEl.textContent = fmt(audio.currentTime);
    });

    toggle.addEventListener('click', function () {
      if (audio.paused) { audio.play().catch(function () {}); } else { audio.pause(); }
    });
  }

  // ------------------------------------------------------------------ chrome

  function bindChrome() {
    var searchInput = document.getElementById('search');
    var t = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(t);
      t = setTimeout(function () { runSearch(searchInput.value.trim()); }, 200);
    });
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { searchInput.value = ''; clearSearch(); }
      if (e.key === 'Enter') {
        e.preventDefault();
        focusMatch(matchIndex + (e.shiftKey ? -1 : 1));
      }
    });
    document.getElementById('search-next').addEventListener('click', function () {
      focusMatch(matchIndex + 1);
    });
    document.getElementById('search-prev').addEventListener('click', function () {
      focusMatch(matchIndex - 1);
    });

    document.getElementById('toggle-flags').addEventListener('click', function () {
      setFlags(!state.flags);
      save();
    });

    document.getElementById('toggle-theme').addEventListener('click', function () {
      var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      state.theme = next;
      save();
    });

    var register = document.getElementById('register');
    register.addEventListener('change', function () {
      setRegister(register.value);
      save();
    });

    document.getElementById('export').addEventListener('click', exportCopy);

    window.addEventListener('beforeunload', function (e) {
      if (!exported && Object.keys(state.turns).length) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  function setRegister(name) {
    state.register = name;
    document.documentElement.dataset.register = name;
    document.getElementById('style-document').disabled = (name !== 'document');
    document.getElementById('style-console').disabled = (name !== 'console');
    document.getElementById('register').value = name;
  }

  // ------------------------------------------------------------------- init

  load();
  bindEditing();
  bindSpeakers();
  bindPlain();
  bindAudio();
  bindChrome();

  applyEdits();
  document.querySelectorAll('.speakers').forEach(function (s) { applyNames(s.dataset.file); });
  Object.keys(state.opts).forEach(function (file) {
    var panel = document.querySelector('.source[data-file="' + file + '"] .plain');
    if (!panel) { return; }
    panel.querySelector('.opt-ts').checked = state.opts[file].ts;
    panel.querySelector('.opt-spk').checked = state.opts[file].spk;
  });
  document.querySelectorAll('.source').forEach(rebuildPlain);

  if (state.theme) { document.documentElement.dataset.theme = state.theme; }
  setRegister(state.register || 'document');
  if (state.flags) { setFlags(true); }
  setStatus('saved');
})();
