  // --------------------------------------------------------------- speakers

  function applyNames(fileIndex) {
    var names = state.names[fileIndex] || {};
    var section = sectionFor(fileIndex);
    var strip = stripFor(fileIndex);

    if (section) {
      section.querySelectorAll('.spk').forEach(function (el) {
        var i = el.dataset.speaker;
        // dataset.fallback carries the already-translated "Speaker N" produced
        // by the renderer - this process has no way to build it itself.
        el.textContent = (names[i] && names[i].trim()) || el.dataset.fallback || '';
      });
      rebuildPlain(section);
    }

    // The name inputs moved into the sidebar's speaker roster (.speakers)
    // two rounds ago; .source only ever holds the read-only .spk chips
    // above. Querying .speaker-name inside .source used to find nothing,
    // which is why "use these names in all files" repainted the chips but
    // left every other file's sidebar input showing its old value.
    if (strip) {
      strip.querySelectorAll('.speaker-name').forEach(function (input) {
        var i = input.closest('.speaker-row').dataset.speaker;
        if (document.activeElement !== input) { input.value = names[i] || ''; }
      });
    }
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
    var btn = el('button', 'swatch-trigger', {
      'aria-haspopup': 'true',
      'aria-expanded': 'false',
      'aria-label': t('speaker_colour', 'Speaker colour'),
    });
    btn.type = 'button';
    // Own class, not .swatch - see the CSS comment on .swatch-rest and the
    // matching one in formatting.py's _swatch_trigger_html() for why this
    // has to stay a different class from the popover's per-colour dots
    // rather than merely a differently-scoped selector.
    var dot = el('span', 'swatch-rest', { 'aria-hidden': 'true' });
    btn.appendChild(dot);
    return btn;
  }

  // Builds one .speaker-row from scratch - used both when a speaker is added
  // live and when applySpeakerState() replays an added speaker on reload, so
  // the two paths produce identical markup rather than two hand-maintained
  // copies of the same shape.
  function createSpeakerRow(strip, id, fallback, palette) {
    var row = el('div', 'speaker-row');
    row.dataset.speaker = String(id);
    row.dataset.palette = String(palette);

    row.appendChild(buildSwatchTrigger());

    var input = el('input', 'speaker-name', { 'aria-label': fallback });
    input.type = 'text';
    input.placeholder = fallback;
    row.appendChild(input);

    var anchor = strip.querySelector('.apply-all') || strip.querySelector('.add-speaker');
    strip.insertBefore(row, anchor);
    bindSpeakerRow(row, strip.dataset.file);
    return row;
  }

  function addSpeaker(fileIndex) {
    var strip = stripFor(fileIndex);
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

    var section = sectionFor(fileIndex);
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
    var menu = el('div', 'spk-menu', { role: 'menu', 'aria-label': t('reassign', 'Reassign to') });

    var strip = stripFor(fileIndex);
    if (!strip) { return menu; }

    strip.querySelectorAll('.speaker-row').forEach(function (row) {
      var id = row.dataset.speaker;
      var nameInput = row.querySelector('.speaker-name');
      var name = (nameInput.value && nameInput.value.trim()) || nameInput.placeholder;
      var palette = row.dataset.palette;

      var item = el('button', 'spk-menu-item', {
        role: 'menuitemradio',
        'aria-checked': String(id === currentId),
      });
      item.type = 'button';
      item.dataset.speaker = id;
      item.dataset.palette = palette;

      var dot = el('span', 'swatch', { 'aria-hidden': 'true' });
      dot.dataset.palette = palette;
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
    var menu = el('div', 'swatch-menu', { role: 'menu', 'aria-label': t('speaker_colour', 'Speaker colour') });

    for (var i = 0; i < 8; i++) {
      var item = el('button', 'swatch-menu-item', {
        role: 'menuitemradio',
        'aria-checked': String(i === currentPalette),
        'aria-label': t('speaker_colour', 'Speaker colour') + ' ' + (i + 1),
      });
      item.type = 'button';
      item.dataset.palette = String(i);

      var dot = el('span', 'swatch', { 'aria-hidden': 'true' });
      dot.dataset.palette = String(i);
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

  // The .turn currently raised above its siblings because it holds an open
  // .spk-menu - see .turn.menu-open in transcript.css for why this has to
  // be an explicit class transcript.js owns, rather than a :hover rule: the
  // menu stays open after the pointer leaves the card, so a hover-keyed
  // z-index would drop the card back underneath its next sibling at exactly
  // the moment the menu is being used, not before.
  var menuOpenTurn = null;

  function closeMenu() {
    var menus = document.querySelectorAll('.spk-menu, .swatch-menu');
    // Keyboard users who have moved focus into the menu (its first item is
    // focused on open - see toggleMenu()'s own first.focus() below) lose
    // their place entirely once the menu is removed from the DOM: focus
    // silently falls back to <body>, with nothing announced and nowhere to
    // Tab from. bindHelp()'s openHelp()/closeHelp() pair already solves the
    // same problem for the help panel and tour card by capturing the
    // trigger on open and refocusing it on close - reused here rather than
    // inventing a second pattern, with one difference the menus need and
    // the panels don't: closeMenu() doubles as bindMenus()'s catch-all for
    // "the reader clicked somewhere else entirely", where focus has already
    // landed on whatever was clicked. Refocusing the trigger unconditionally
    // there would fight that click, so the restore only fires when focus
    // was actually inside the menu being torn down - true after Escape or
    // after activating a menu item, false after a click elsewhere.
    var focusWasInMenu = openMenuBtn && Array.prototype.some.call(menus, function (m) {
      return m.contains(document.activeElement);
    });
    menus.forEach(function (m) { m.remove(); });
    if (openMenuBtn) {
      openMenuBtn.setAttribute('aria-expanded', 'false');
      if (focusWasInMenu) { openMenuBtn.focus(); }
    }
    if (menuOpenTurn) { menuOpenTurn.classList.remove('menu-open'); menuOpenTurn = null; }
    openMenuBtn = null;
  }

  // Escaping .outline's overflow-y: auto is only a concern while the
  // popover is actually detached from it - see positionDetachedMenu() and
  // the .swatch-menu comment in transcript.css for why a fixed-position
  // popover has to close on scroll instead of trying to follow the trigger:
  // it has no DOM relationship to the scrolled container to follow it with.
  document.addEventListener('scroll', function (e) {
    if (!openMenuBtn) { return; }
    var menu = document.querySelector('.swatch-menu');
    if (menu && e.target.contains && e.target.contains(openMenuBtn)) { closeMenu(); }
  }, true);

  // Reads the target's real on-screen box via getBoundingClientRect() and
  // writes it back as fixed, physical left/top - not inset-inline-start,
  // unlike everywhere else in this file. Logical properties describe a
  // position relative to a box's own writing direction; a rect from
  // getBoundingClientRect() is already a physical viewport measurement with
  // no writing-direction of its own to be logical *about*, so resolving
  // "which physical side is inline-start" has to happen here explicitly
  // instead (via getComputedStyle(target).direction) rather than being free,
  // the way it is for anything actually laid out by the CSS box model.
  //
  // Originally written only for the two popovers (.spk-menu, .swatch-menu),
  // both anchored to a small <button>. The guided tour reuses this as-is for
  // its caption card, anchored instead to whatever element the current step
  // is pointing at - a plain rename from `btn` to `target` is the only
  // change that reuse needed, since getBoundingClientRect() and
  // getComputedStyle() work identically on any element, button or not.
  function positionDetachedMenu(menu, target) {
    var rect = target.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = (rect.bottom + 4) + 'px';
    var rtl = getComputedStyle(target).direction === 'rtl';
    // clientWidth, NOT window.innerWidth. innerWidth includes the scrollbar
    // gutter; a fixed element's containing block does not. Mixing the two
    // put the menu exactly one scrollbar-width (16px here) inline-start of
    // its trigger on every scrollable page - which, since this document
    // always scrolls, meant always. getBoundingClientRect() is already in
    // client coordinates, so the number subtracted from it has to be too.
    if (rtl) {
      menu.style.right = (document.documentElement.clientWidth - rect.right) + 'px';
    } else {
      menu.style.left = rect.left + 'px';
    }

    // Clamp to the viewport rather than letting the grid run off the bottom
    // edge - the whole point of detaching this popover was to stop an
    // ancestor's box from clipping it, so it would be self-defeating to
    // leave it clipped by the one box every page has: the viewport itself.
    var menuRect = menu.getBoundingClientRect();
    if (menuRect.bottom > window.innerHeight) {
      menu.style.top = (rect.top - menuRect.height - 4) + 'px';
    }

    // Horizontal clamp, added for the tour card and never exercised by the
    // two original callers: a popover's trigger is always a small button
    // comfortably inside the viewport, but a tour step's target can be as
    // wide as the whole toolbar row (.file-bar) or as tall and off to one
    // side as the sidebar (.outline), so the plain "start flush with the
    // target's own edge" placement above can push the card partway off the
    // opposite side of the screen. Re-measured after the vertical flip
    // above (which only ever changes `top`), and nudged into
    // [8px, viewport width - card width - 8px] the same "clamp to the
    // viewport, not an ancestor's box" reasoning as the vertical case.
    //
    // Which CSS property gets nudged has to follow the same `rtl` branch the
    // anchoring above used, not default to `left` unconditionally - the
    // first version of this clamp always wrote menu.style.left and blanked
    // menu.style.right, which silently overwrote the RTL branch's own
    // `right` positioning for any popover that tripped the clamp. That is
    // invisible in an LTR document (the clamp's `left` write is exactly
    // what the anchor above already used) but misplaces the popover in this
    // RTL-first app: an element anchored from its inline-start (physically
    // its right edge, in RTL) would end up pinned by `left` instead,
    // sliding to the opposite side of its trigger. Writing back into
    // whichever property (`right` for RTL, `left` for LTR) anchored the
    // popover in the first place keeps the clamp a pure "pull back onto
    // screen" adjustment rather than a second, conflicting placement.
    menuRect = menu.getBoundingClientRect();
    if (menuRect.left < 8) {
      if (rtl) {
        menu.style.right = (document.documentElement.clientWidth - menuRect.width - 8) + 'px';
      } else {
        menu.style.left = '8px';
        menu.style.right = '';
      }
    } else if (menuRect.right > document.documentElement.clientWidth - 8) {
      if (rtl) {
        menu.style.right = '8px';
      } else {
        menu.style.left = (document.documentElement.clientWidth - menuRect.width - 8) + 'px';
        menu.style.right = '';
      }
    }
  }

  // buildFn is called fresh on every open, not memoised - see
  // buildSpeakerMenu()/buildSwatchMenu()'s own comments for why a rebuilt
  // menu can never show a stale roster or a stale colour.
  function toggleMenu(btn, buildFn) {
    var reopening = btn !== openMenuBtn;
    closeMenu();
    if (!reopening) { return; }

    var menu = buildFn();
    if (menu.classList.contains('swatch-menu')) {
      // See the .swatch-menu comment in transcript.css: .speaker-row lives
      // inside .outline's overflow-y: auto, which would otherwise clip this
      // popover at the sidebar's edge. Appending to <body> removes it from
      // that clipped subtree entirely instead of trying to out-z-index or
      // out-overflow an ancestor that will always win.
      document.body.appendChild(menu);
      positionDetachedMenu(menu, btn);
    } else {
      btn.insertAdjacentElement('afterend', menu);
      if (menu.classList.contains('spk-menu')) {
        menuOpenTurn = btn.closest('.turn');
        if (menuOpenTurn) { menuOpenTurn.classList.add('menu-open'); }
      }
    }
    btn.setAttribute('aria-expanded', 'true');
    openMenuBtn = btn;
    var first = menu.querySelector('[role="menuitemradio"]');
    if (first) { first.focus(); }
  }

  function reassignTurn(turn, newId, newPalette) {
    var section = turn.closest('.source');
    var fileIndex = section.dataset.file;
    var strip = stripFor(fileIndex);
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
        // Not swatchItem.closest('.swatch-menu').closest('.speaker-row'):
        // the menu is detached to <body> while open (see toggleMenu() and
        // the .swatch-menu comment in transcript.css), so it is no longer a
        // DOM descendant of the row that opened it. openMenuBtn - the
        // .swatch-trigger itself - never moves, so it is the one thing
        // still reliably inside .speaker-row to recover it from. Read
        // before closeMenu() clears openMenuBtn.
        var swatchRow = openMenuBtn ? openMenuBtn.closest('.speaker-row') : null;
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
      var strip = stripFor(fileIndex);
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
      var strip = stripFor(section.dataset.file);
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
