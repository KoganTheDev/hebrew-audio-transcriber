/* ===========================================================================
   Transcript document behaviour.

   Inlined into the generated HTML by core/formatting.py. Kept as a real .js
   file rather than a Python string so it stays lintable and readable.

   The document is opened from file://, which cannot write back to itself -
   browsers block that, and the File System Access API is unavailable because
   file:// documents have an opaque origin. So "autosave" means localStorage,
   and "Save a copy" downloads a fresh HTML with the edits baked in. Every
   design decision below follows from that one constraint.

   Written as ES5-style classic script on purpose: it is loaded inline from a
   file:// page, where ES modules are blocked.
   =========================================================================== */
(function () {
  'use strict';

  var payloadEl = document.getElementById('transcript-data');
  if (!payloadEl) { return; }

  var DATA = JSON.parse(payloadEl.textContent);
  var STR = DATA.strings || {};
  var DOC_ID = document.documentElement.dataset.docId;
  var KEY = 'hebrew-transcript:' + DOC_ID;

  // speakers[fileIndex][id] = {fallback, palette, added} - added speakers
  // need their whole row reconstructed on reload (nothing in the HTML made
  // one for them); recoloured *original* speakers only need their palette
  // restored, so `added` is left off that entry and applySpeakerState()
  // treats its absence as "the row already exists, just repaint it".
  // assign[turnId] = speaker id - set only for turns whose speaker has been
  // changed since render, so a reload knows to move them off the id the
  // server gave them.
  var state = {
    turns: {}, names: {}, flags: false, theme: null, opts: {},
    speakers: {}, assign: {},
  };
  var exported = true;
  var saveTimer = null;
  var statusEl = document.getElementById('status');

  function t(key, fallback) { return STR[key] || fallback || key; }

  // Smooth scrolling is motion, and a reader who has asked the system for less
  // of it means this too - CSS scroll-behavior does not govern scrollIntoView's
  // explicit option, so it has to be checked here.
  function scrollBehavior() {
    return window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 'auto' : 'smooth';
  }

  // ---------------------------------------------------------------- storage

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { state = Object.assign(state, JSON.parse(raw)); }
    } catch (e) {
      // Storage disabled, quota exhausted, or a corrupt entry. Losing restored
      // edits is bad; a document that refuses to open is worse.
      console.warn('could not read saved edits', e);
    }
  }

  function hasLocalChanges() {
    return Object.keys(state.turns).length > 0 || Object.keys(state.names).length > 0
      || Object.keys(state.speakers).length > 0 || Object.keys(state.assign).length > 0;
  }

  function save() {
    setStatus('saving');
    clearTimeout(saveTimer);
    // Debounced so a fast typist writes once per pause, not once per keystroke.
    saveTimer = setTimeout(function () {
      try {
        localStorage.setItem(KEY, JSON.stringify(state));
        exported = false;
        setStatus('local');
      } catch (e) {
        setStatus('error');
      }
    }, 400);
  }

  function setStatus(kind) {
    if (!statusEl) { return; }
    // "local" is the honest state and the one the reader is usually in: the
    // edit is safely in this browser, but the .html on disk does not contain
    // it and will not until "Save a copy" is used. Reporting a plain "Saved"
    // there would imply the file had been updated, which is exactly the thing
    // a file:// page cannot do.
    statusEl.textContent = {
      saving: t('status_saving', 'Saving…'),
      saved: t('status_saved', 'Saved'),
      local: t('status_local', 'Saved in browser'),
      error: t('status_error', 'Could not save')
    }[kind];
    statusEl.dataset.kind = kind;
  }

  // ------------------------------------------------------------------ edits

  function eachTurn(fn) { document.querySelectorAll('.turn').forEach(fn); }

  // Edits are stored as an array of plain paragraph strings, never as raw
  // innerHTML. Markup pasted from another app would otherwise be persisted and
  // re-injected verbatim on the next load, and a transcript has no use for
  // rich text - the plain-text panel is the whole point of the document.
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

  // --------------------------------------------------------------- speakers

  function applyNames(fileIndex) {
    var names = state.names[fileIndex] || {};
    var section = document.querySelector('.source[data-file="' + fileIndex + '"]');
    if (!section) { return; }

    section.querySelectorAll('.spk').forEach(function (el) {
      var i = el.dataset.speaker;
      // dataset.fallback carries the already-translated "Speaker N" produced
      // by the renderer - this process has no way to build it itself.
      el.textContent = (names[i] && names[i].trim()) || el.dataset.fallback || '';
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

      strip.querySelectorAll('.speaker-row').forEach(function (row) {
        bindSpeakerRow(row, fileIndex);
      });

      var addBtn = strip.querySelector('.add-speaker');
      if (addBtn) {
        addBtn.addEventListener('click', function () { addSpeaker(fileIndex); });
      }

      var applyAll = strip.querySelector('.apply-all');
      if (!applyAll) { return; }
      applyAll.addEventListener('click', function () {
        var source = state.names[fileIndex] || {};
        document.querySelectorAll('.speakers').forEach(function (other) {
          var target = other.dataset.file;
          if (target === fileIndex) { return; }
          state.names[target] = state.names[target] || {};
          // Only fill speakers that actually exist in the other recording, so
          // a three-speaker file never invents a third name in a two-speaker
          // one.
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

  // Shared by every .speaker-row, whether it was rendered by formatting.py or
  // created on the fly by addSpeaker() / replayed by applySpeakerState() -
  // one binding path so the two can never drift into different behaviour.
  // Recolouring itself is handled by the delegated click listener in
  // bindMenus() (the row's .swatch-trigger opens a popover, same shape as a
  // turn's .spk), so this only has the name input left to wire up.
  function bindSpeakerRow(row, fileIndex) {
    var input = row.querySelector('.speaker-name');
    input.addEventListener('input', function () {
      var i = row.dataset.speaker;
      state.names[fileIndex] = state.names[fileIndex] || {};
      state.names[fileIndex][i] = input.value;
      applyNames(fileIndex);
      save();
    });
  }

  function buildSwatchTrigger() {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'swatch-trigger';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-label', t('speaker_colour', 'Speaker colour'));
    var dot = document.createElement('span');
    dot.className = 'swatch';
    dot.setAttribute('aria-hidden', 'true');
    btn.appendChild(dot);
    return btn;
  }

  // Builds one .speaker-row from scratch - used both when a speaker is added
  // live and when applySpeakerState() replays an added speaker on reload, so
  // the two paths produce identical markup rather than two hand-maintained
  // copies of the same shape.
  function createSpeakerRow(strip, id, fallback, palette) {
    var row = document.createElement('div');
    row.className = 'speaker-row';
    row.dataset.speaker = String(id);
    row.dataset.palette = String(palette);

    row.appendChild(buildSwatchTrigger());

    var input = document.createElement('input');
    input.className = 'speaker-name';
    input.type = 'text';
    input.placeholder = fallback;
    input.setAttribute('aria-label', fallback);
    row.appendChild(input);

    var anchor = strip.querySelector('.apply-all') || strip.querySelector('.add-speaker');
    strip.insertBefore(row, anchor);
    bindSpeakerRow(row, strip.dataset.file);
    return row;
  }

  function addSpeaker(fileIndex) {
    var strip = document.querySelector('.speakers[data-file="' + fileIndex + '"]');
    if (!strip) { return; }

    var maxId = -1;
    var count = 0;
    strip.querySelectorAll('.speaker-row').forEach(function (row) {
      maxId = Math.max(maxId, Number(row.dataset.speaker));
      count++;
    });
    var id = maxId + 1;
    var palette = count % 8;
    var template = DATA.speakerLabel || 'Speaker {n}';
    var fallback = template.replace('{n}', String(count + 1));

    state.speakers[fileIndex] = state.speakers[fileIndex] || {};
    state.speakers[fileIndex][id] = { fallback: fallback, palette: palette, added: true };

    createSpeakerRow(strip, id, fallback, palette);
    save();
  }

  // Recolouring is a property of the *speaker*, not of any one turn: every
  // turn currently carrying this identity has to repaint together, which is
  // why this walks the section rather than touching a single element. The
  // row's own dot repaints for free - it's coloured by .speaker-row's own
  // data-palette in CSS, not by anything this function touches directly.
  function recolourSpeaker(fileIndex, row, palette) {
    var id = row.dataset.speaker;
    row.dataset.palette = String(palette);

    state.speakers[fileIndex] = state.speakers[fileIndex] || {};
    var entry = state.speakers[fileIndex][id] || {};
    entry.palette = palette;
    state.speakers[fileIndex][id] = entry;

    var section = document.querySelector('.source[data-file="' + fileIndex + '"]');
    if (section) {
      section.querySelectorAll('.turn[data-speaker="' + id + '"]').forEach(function (turn) {
        turn.dataset.palette = String(palette);
        var spk = turn.querySelector('.spk');
        if (spk) { spk.dataset.palette = String(palette); }
      });
    }
    save();
  }

  // Builds the reassignment menu fresh from the current speaker roster every
  // time it opens, rather than keeping a parallel copy in sync - a speaker
  // added or renamed after the page loaded is picked up automatically.
  function buildSpeakerMenu(fileIndex, currentId) {
    var menu = document.createElement('div');
    menu.className = 'spk-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', t('reassign', 'Reassign to'));

    var strip = document.querySelector('.speakers[data-file="' + fileIndex + '"]');
    if (!strip) { return menu; }

    strip.querySelectorAll('.speaker-row').forEach(function (row) {
      var id = row.dataset.speaker;
      var nameInput = row.querySelector('.speaker-name');
      var name = (nameInput.value && nameInput.value.trim()) || nameInput.placeholder;
      var palette = row.dataset.palette;

      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'spk-menu-item';
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(id === currentId));
      item.dataset.speaker = id;
      item.dataset.palette = palette;

      var dot = document.createElement('span');
      dot.className = 'swatch';
      dot.dataset.palette = palette;
      dot.setAttribute('aria-hidden', 'true');
      item.appendChild(dot);
      item.appendChild(document.createTextNode(name));
      menu.appendChild(item);
    });

    return menu;
  }

  // Builds the colour popover fresh from the row's current palette every
  // time it opens - same "no parallel copy to go stale" reasoning as
  // buildSpeakerMenu() above, and the same popover shape (a
  // built-on-demand, torn-down-on-close overlay) rather than a second
  // interaction pattern invented just for colour.
  function buildSwatchMenu(row, currentPalette) {
    var menu = document.createElement('div');
    menu.className = 'swatch-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', t('speaker_colour', 'Speaker colour'));

    for (var i = 0; i < 8; i++) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'swatch-menu-item';
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(i === currentPalette));
      item.dataset.palette = String(i);
      item.setAttribute('aria-label', t('speaker_colour', 'Speaker colour') + ' ' + (i + 1));

      var dot = document.createElement('span');
      dot.className = 'swatch';
      dot.dataset.palette = String(i);
      dot.setAttribute('aria-hidden', 'true');
      item.appendChild(dot);
      menu.appendChild(item);
    }

    return menu;
  }

  // One open-popover tracker shared by both menu kinds (.spk-menu and
  // .swatch-menu) - they never need to be open at once, and a reader
  // opening one always expects the other to close, the same way any menu
  // system dismisses its sibling rather than stacking.
  var openMenuBtn = null;

  function closeMenu() {
    document.querySelectorAll('.spk-menu, .swatch-menu').forEach(function (m) { m.remove(); });
    if (openMenuBtn) { openMenuBtn.setAttribute('aria-expanded', 'false'); }
    openMenuBtn = null;
  }

  // buildFn is called fresh on every open, not memoised - see
  // buildSpeakerMenu()/buildSwatchMenu()'s own comments for why a rebuilt
  // menu can never show a stale roster or a stale colour.
  function toggleMenu(btn, buildFn) {
    var reopening = btn !== openMenuBtn;
    closeMenu();
    if (!reopening) { return; }

    var menu = buildFn();
    btn.insertAdjacentElement('afterend', menu);
    btn.setAttribute('aria-expanded', 'true');
    openMenuBtn = btn;
    var first = menu.querySelector('[role="menuitemradio"]');
    if (first) { first.focus(); }
  }

  function reassignTurn(turn, newId, newPalette) {
    var section = turn.closest('.source');
    var fileIndex = section.dataset.file;
    var strip = document.querySelector('.speakers[data-file="' + fileIndex + '"]');
    var row = strip && strip.querySelector('.speaker-row[data-speaker="' + newId + '"]');
    var fallback = row ? row.querySelector('.speaker-name').placeholder : '';

    turn.dataset.speaker = newId;
    turn.dataset.palette = newPalette;
    var spk = turn.querySelector('.spk');
    if (spk) {
      spk.dataset.speaker = newId;
      spk.dataset.palette = newPalette;
      spk.dataset.fallback = fallback;
    }

    state.assign[turn.dataset.turn] = Number(newId);
    // applyNames repaints every .spk in the file from state.names/fallback,
    // which already covers this turn now that its data-speaker points at the
    // new identity - no separate "set this one label" path needed.
    applyNames(fileIndex);
    rebuildPlain(section);
    save();
  }

  // Delegated, not bound per-button: both a turn's .spk and a speaker row's
  // .swatch-trigger, plus the popovers either one opens, are handled by this
  // one listener - added speakers get the same behaviour as rendered ones
  // for free, with nothing new to bind when a row is created later.
  function bindMenus() {
    document.addEventListener('click', function (e) {
      var spkBtn = e.target.closest ? e.target.closest('.spk') : null;
      if (spkBtn) {
        e.stopPropagation();
        toggleMenu(spkBtn, function () {
          var turn = spkBtn.closest('.turn');
          var fileIndex = turn.closest('.source').dataset.file;
          return buildSpeakerMenu(fileIndex, turn.dataset.speaker);
        });
        return;
      }

      var swatchBtn = e.target.closest ? e.target.closest('.swatch-trigger') : null;
      if (swatchBtn) {
        e.stopPropagation();
        var row = swatchBtn.closest('.speaker-row');
        toggleMenu(swatchBtn, function () {
          return buildSwatchMenu(row, Number(row.dataset.palette));
        });
        return;
      }

      var item = e.target.closest ? e.target.closest('.spk-menu-item') : null;
      if (item) {
        var menu = item.closest('.spk-menu');
        var turn = menu ? menu.closest('.turn') : null;
        closeMenu();
        if (turn) { reassignTurn(turn, item.dataset.speaker, item.dataset.palette); }
        return;
      }

      var swatchItem = e.target.closest ? e.target.closest('.swatch-menu-item') : null;
      if (swatchItem) {
        var swatchMenu = swatchItem.closest('.swatch-menu');
        var swatchRow = swatchMenu ? swatchMenu.closest('.speaker-row') : null;
        closeMenu();
        if (swatchRow) {
          var fileIndex = swatchRow.closest('.speakers').dataset.file;
          recolourSpeaker(fileIndex, swatchRow, Number(swatchItem.dataset.palette));
        }
        return;
      }

      closeMenu();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { closeMenu(); }
    });
  }

  // Replays added speakers and speaker recolours saved in a previous session
  // - applyEdits()'s counterpart for the speaker roster. Has to run before
  // applyAssignments() and applyNames(): a reassignment can point at a
  // speaker that only exists because this function just recreated it.
  function applySpeakerState() {
    Object.keys(state.speakers).forEach(function (fileIndex) {
      var strip = document.querySelector('.speakers[data-file="' + fileIndex + '"]');
      if (!strip) { return; }
      var entries = state.speakers[fileIndex];
      Object.keys(entries).forEach(function (id) {
        var entry = entries[id];
        var row = strip.querySelector('.speaker-row[data-speaker="' + id + '"]');
        if (!row && entry.added) {
          row = createSpeakerRow(strip, Number(id), entry.fallback || '', entry.palette || 0);
        }
        // The dot's colour is driven entirely by the row's own data-palette
        // (see .speaker-row[data-palette] in transcript.css) - nothing else
        // on the row needs updating to reflect a recolour.
        if (row && typeof entry.palette === 'number') {
          row.dataset.palette = String(entry.palette);
        }
      });
    });
  }

  // Replays turn reassignments saved in a previous session.
  function applyAssignments() {
    Object.keys(state.assign).forEach(function (turnId) {
      var turn = document.querySelector('.turn[data-turn="' + turnId + '"]');
      if (!turn) { return; }
      var newId = String(state.assign[turnId]);
      var section = turn.closest('.source');
      var strip = document.querySelector('.speakers[data-file="' + section.dataset.file + '"]');
      var row = strip && strip.querySelector('.speaker-row[data-speaker="' + newId + '"]');
      var palette = row ? row.dataset.palette : newId;
      var fallback = row ? row.querySelector('.speaker-name').placeholder : null;

      turn.dataset.speaker = newId;
      turn.dataset.palette = palette;
      var spk = turn.querySelector('.spk');
      if (spk) {
        spk.dataset.speaker = newId;
        spk.dataset.palette = palette;
        if (fallback !== null) { spk.dataset.fallback = fallback; }
      }
    });
  }

  // ------------------------------------------------------------- plain text

  function turnPlainText(turn, withTs, withSpk) {
    var prefix = [];
    var ts = turn.querySelector('.ts');
    var spk = turn.querySelector('.spk');
    if (withTs && ts) { prefix.push(ts.textContent.trim()); }
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

  function rebuildPlain(section) {
    if (!section) { return; }
    var panel = section.querySelector('.plain');
    if (!panel) { return; }

    var tsBox = panel.querySelector('.opt-ts');
    var spkBox = panel.querySelector('.opt-spk');
    var withTs = tsBox ? tsBox.checked : false;
    var withSpk = spkBox ? spkBox.checked : false;

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

  // ------------------------------------------------- low-confidence shading

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
        var span = document.createElement('span');
        span.className = 'lowconf';
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
    eachTurn(on ? flagTurn : unflagTurn);
  }

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
    if (!el) { return; }
    el.textContent = matches.length
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

  // ----------------------------------------------------------------- export

  function exportCopy() {
    clearSearch();
    var wasFlagged = state.flags;
    if (wasFlagged) { setFlags(false); }

    // Serialising reads attributes, but typing only updates properties, so
    // form state has to be written back before it can survive the export.
    bakeFormState();

    // Strip transient view state so the exported file opens in its resting
    // state rather than frozen mid-session: a half-typed query, a player
    // pointing at an audio path that only made sense on this machine, panels
    // left open. None of it is content.
    var restore = resetTransientState();

    // The live DOM already holds the edits and names, so serialising it is the
    // export. The result is itself a working editor with the same doc id, so
    // editing can continue in the downloaded copy.
    var html = '<!doctype html>\n' + document.documentElement.outerHTML;
    restore();
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (DATA.filename || 'transcript') + ' (edited).html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    if (wasFlagged) { setFlags(true); }
    exported = true;
    setStatus('saved');
  }

  function bakeFormState() {
    // Without this the exported copy carries speaker names in the turn labels
    // but an empty name box, and on a machine with no saved state the first
    // edit would read that empty box and reset the name to its fallback. The
    // exported file has to stand on its own.
    document.querySelectorAll('.speaker-name').forEach(function (input) {
      input.setAttribute('value', input.value);
    });
    document.querySelectorAll('.plain input[type="checkbox"]').forEach(function (box) {
      if (box.checked) {
        box.setAttribute('checked', '');
      } else {
        box.removeAttribute('checked');
      }
    });
  }

  function resetTransientState() {
    var searchInput = document.getElementById('search');
    var player = document.getElementById('player');
    var audio = document.getElementById('audio');
    var count = document.getElementById('search-count');

    var previous = {
      query: searchInput ? searchInput.value : '',
      audioSrc: audio ? audio.getAttribute('src') : null,
      playerHidden: player ? player.hidden : true
    };

    if (searchInput) { searchInput.value = ''; }
    if (count) { count.textContent = ''; }
    if (player) { player.hidden = true; }
    // Remove the attribute rather than blanking it: src="" resolves to the
    // document URL, which makes the browser try to play the HTML itself.
    if (audio) { audio.removeAttribute('src'); }
    // The plain-text panel is always visible now (see _render_plain_html's
    // docstring) - there is no open/closed state left to reset here.

    return function () {
      if (searchInput) { searchInput.value = previous.query; }
      if (player) { player.hidden = previous.playerHidden; }
      if (audio && previous.audioSrc) { audio.setAttribute('src', previous.audioSrc); }
    };
  }

  // ------------------------------------------------------------------ audio

  function bindAudio() {
    var audio = document.getElementById('audio');
    var player = document.getElementById('player');
    if (!audio || !player) { return; }

    var fileEl = document.getElementById('player-file');
    var timeEl = document.getElementById('player-time');
    var toggle = document.getElementById('player-toggle');
    var current = null;
    var currentSection = null;
    // The end of the range a .ts click asked to hear, or null when playback
    // is free-running (the reader pressed the toggle, or nothing bounded has
    // been clicked yet). Read by the unthrottled stop-check in the
    // timeupdate handler below, and by the toggle handler that clears it.
    var boundEnd = null;

    function fmt(s) {
      var m = Math.floor(s / 60), r = Math.floor(s % 60);
      return m + ':' + (r < 10 ? '0' : '') + r;
    }

    document.querySelectorAll('.ts').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var section = btn.closest('.source');
        var file = section.dataset.audio;
        if (!file) { return; }

        player.hidden = false;
        fileEl.textContent = file;
        if (current !== file) {
          current = file;
          currentSection = section;
          audio.src = encodeURIComponent(file);
        }
        audio.currentTime = Number(btn.dataset.start);
        boundEnd = Number(btn.dataset.end);
        audio.play().catch(function () { /* the error listener handles it */ });
      });
    });

    audio.addEventListener('error', function () {
      // The audio was moved away from the transcript, or the container is one
      // the browser cannot play (.mkv, for instance). Playback is an extra, so
      // it removes itself rather than showing a broken control.
      player.hidden = true;
      if (!currentSection) { return; }

      // Only the recording that actually failed is marked. A batch routinely
      // mixes files that play with ones that do not - a missing .mkv must not
      // take the other transcripts' playback down with it, and this handler
      // fires per failed load, so a document-wide flag would be permanent
      // after the first bad file.
      currentSection.dataset.noAudio = 'true';

      // The CSS strips the button chrome and pointer cursor (see
      // .source[data-no-audio] .ts), but a visual change alone leaves the
      // control reachable by Tab and announced as a button to a screen
      // reader - both would still promise an action that no longer happens.
      // disabled removes it from the tab order and native click handling;
      // aria-disabled is set alongside it because some assistive tech
      // announces "dimmed"/"unavailable" from aria-disabled specifically.
      currentSection.querySelectorAll('.ts').forEach(function (btn) {
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
      });

      // Let the next click start clean rather than short-circuiting on the
      // src it failed to load.
      current = null;
      currentSection = null;
      boundEnd = null;
    });

    // timeupdate fires several times a second. The clock is cheap, but
    // re-deciding which turn is playing walks the section, so that part is
    // throttled to roughly four times a second - fast enough to feel live,
    // slow enough to stay off the main thread's budget. The range-stop check
    // is a single number comparison, cheap enough to run on every event
    // rather than share that throttle - and it has to: at 250ms resolution a
    // short turn could finish playing before the throttled sweep ever looks,
    // overshooting well past its end. A setTimeout timed to the range's
    // length was the other option and was rejected - it would race whatever
    // called pause() or changed currentTime in between, firing a stale stop
    // after a reader had already sought elsewhere. Overshoot here is bounded
    // by one timeupdate tick (browsers fire it roughly every ~250ms), which
    // reads as "stopped right around there," not as a bug.
    var lastSweep = 0;
    var playing = null;

    audio.addEventListener('timeupdate', function () {
      timeEl.textContent = fmt(audio.currentTime);

      if (boundEnd !== null && audio.currentTime >= boundEnd) {
        audio.pause();
        audio.currentTime = boundEnd;
        boundEnd = null;
      }

      var now = Date.now();
      if (now - lastSweep < 250) { return; }
      lastSweep = now;
      highlightPlaying(audio.currentTime);
    });

    function highlightPlaying(position) {
      // The section is held as an element reference rather than looked up by
      // its filename - a filename is arbitrary text and has no business being
      // spliced into a selector.
      var section = currentSection;
      if (!section) { return; }

      // The turn being spoken is the last one that started at or before now.
      var found = null;
      section.querySelectorAll('.turn').forEach(function (turn) {
        if (Number(turn.dataset.start) <= position) { found = turn; }
      });
      if (found === playing) { return; }

      if (playing) { delete playing.dataset.playing; }
      playing = found;
      if (playing) { playing.dataset.playing = 'true'; }
    }

    audio.addEventListener('pause', function () {
      if (playing) { delete playing.dataset.playing; }
      playing = null;
    });

    toggle.addEventListener('click', function () {
      // A manual resume is the reader taking the wheel back - the range a
      // .ts click asked to stay inside no longer applies, or the toggle
      // would silently pause them again a moment later for no visible reason.
      boundEnd = null;
      if (audio.paused) { audio.play().catch(function () {}); } else { audio.pause(); }
    });
  }

  // ----------------------------------------------------------------- chrome

  function bindChrome() {
    var searchInput = document.getElementById('search');
    if (searchInput) {
      var timer = null;
      searchInput.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { runSearch(searchInput.value.trim()); }, 200);
      });
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { searchInput.value = ''; clearSearch(); }
        if (e.key === 'Enter') {
          e.preventDefault();
          focusMatch(matchIndex + (e.shiftKey ? -1 : 1));
        }
      });
    }

    var next = document.getElementById('search-next');
    var prev = document.getElementById('search-prev');
    if (next) { next.addEventListener('click', function () { focusMatch(matchIndex + 1); }); }
    if (prev) { prev.addEventListener('click', function () { focusMatch(matchIndex - 1); }); }

    var flags = document.getElementById('toggle-flags');
    if (flags) {
      flags.addEventListener('click', function () { setFlags(!state.flags); save(); });
    }

    var theme = document.getElementById('toggle-theme');
    if (theme) {
      theme.addEventListener('click', function () {
        var nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = nextTheme;
        state.theme = nextTheme;
        save();
      });
    }

    var exportBtn = document.getElementById('export');
    if (exportBtn) { exportBtn.addEventListener('click', exportCopy); }

    window.addEventListener('beforeunload', function (e) {
      // Only nag when there is real work that no file on disk contains yet.
      // Renames count as much as text edits - both are lost if this browser's
      // storage is cleared and no copy was ever exported.
      if (!exported && hasLocalChanges()) {
        e.preventDefault();
        e.returnValue = '';
      }
    });

    function isTextEntry(node) {
      return !!node && (node.isContentEditable
        || node.tagName === 'INPUT' || node.tagName === 'TEXTAREA');
    }

    document.addEventListener('keydown', function (e) {
      // Both the event target and the focused element are consulted: the
      // target can be retargeted (or be the document itself, for a
      // programmatic dispatch), while activeElement always reflects where the
      // caret actually is. Getting this wrong swallows a typed "/" mid-word.
      var typing = isTextEntry(e.target) || isTextEntry(document.activeElement);

      // Ctrl/Cmd+S is what everyone's fingers do when they want the file
      // written. There is no file to write, so it triggers the export, which
      // is the nearest true thing.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        exportCopy();
        return;
      }
      // "/" jumps to search, but not while the reader is mid-word.
      if (e.key === '/' && !typing) {
        e.preventDefault();
        var box = document.getElementById('search');
        if (box) { box.focus(); }
      }
    });
  }

  // ---------------------------------------------------------------- layout

  // The sticky file bar sits below the toolbar (see .file-bar in
  // transcript.css), which wraps onto a second line under ~480px - a fixed
  // number here would drift out of sync with that the first time the
  // toolbar's own height changed, so it's measured instead and republished
  // as a custom property the CSS reads.
  function syncToolbarHeight() {
    var toolbar = document.querySelector('.toolbar');
    if (!toolbar) { return; }
    document.documentElement.style.setProperty('--toolbar-height', toolbar.offsetHeight + 'px');
  }

  // ------------------------------------------------------------------- init

  load();
  bindEditing();
  bindSpeakers();
  bindMenus();
  bindPlain();
  bindAudio();
  bindChrome();

  syncToolbarHeight();
  window.addEventListener('resize', syncToolbarHeight);

  // Speaker roster first (added speakers, recolours), then which speaker
  // each turn belongs to, then text edits, then the labels that read all of
  // it back - each step depends on the DOM state the one before it left.
  applySpeakerState();
  applyAssignments();
  applyEdits();
  document.querySelectorAll('.speakers').forEach(function (s) { applyNames(s.dataset.file); });

  Object.keys(state.opts).forEach(function (file) {
    var panel = document.querySelector('.source[data-file="' + file + '"] .plain');
    if (!panel) { return; }
    var ts = panel.querySelector('.opt-ts');
    var spk = panel.querySelector('.opt-spk');
    if (ts) { ts.checked = state.opts[file].ts; }
    if (spk) { spk.checked = state.opts[file].spk; }
  });
  document.querySelectorAll('.source').forEach(rebuildPlain);

  if (state.theme) { document.documentElement.dataset.theme = state.theme; }
  if (state.flags) { setFlags(true); }

  // Restored edits are in this browser, not in any file - assume the worst and
  // say so, rather than opening on a reassuring "Saved" that might be a lie.
  exported = !hasLocalChanges();
  setStatus(exported ? 'saved' : 'local');
})();
