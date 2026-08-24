  // --------------------------------------------------------------- speakers

  function applyNames(fileIndex) {
    var names = state.names[fileIndex] || {};
    var section = sectionFor(fileIndex);
    var strip = stripFor(fileIndex);

    if (section) {
      // Every bubble carries a chip now - the cluster header that used to
      // hold the only ".spk" is gone (see the review plan's "flat sentence
      // cards" section), and every bubble's own chip is populated at render
      // time, not just an overridden one's - so a plain ".bubble-spk" match
      // (not ".bubble-spk[data-speaker]", which used to exclude an
      // un-overridden bubble because it carried no data-speaker at all)
      // reaches every card that needs repainting on a rename.
      section.querySelectorAll('.bubble-spk').forEach(function (el) {
        var i = el.dataset.speaker;
        var label = el.querySelector('.bubble-spk-label');
        // dataset.fallback carries the already-translated "Speaker N"
        // produced by the renderer - this process has no way to build it
        // itself.
        if (label) { label.textContent = (names[i] && names[i].trim()) || el.dataset.fallback || ''; }
      });
      rebuildPlain(section);
    }

    // The name inputs moved into the sidebar's speaker roster (.speakers)
    // two rounds ago; .source only ever holds the read-only .bubble-spk
    // chips above. Querying .speaker-name inside .source used to find nothing,
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
  // bubble's own .bubble-spk), so this only has the name input left to wire up.
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
      });
      // Every bubble showing this speaker's id - whether that is its
      // block's own default identity or a per-sentence override pointing at
      // it - carries data-speaker now (see _render_bubble_html()'s and
      // paintBubbleOverride()'s own docstrings), so this single selector
      // reaches every card that needs repainting without the turn-level
      // loop above needing to reach into its bubbles itself. Updates both
      // the button's own copy of the palette and the bubble's (52-bubble.css
      // reads --spk off the bubble's own [data-palette]).
      section.querySelectorAll('.bubble-spk[data-speaker="' + id + '"]').forEach(function (btn) {
        btn.dataset.palette = String(palette);
        var bubble = btn.closest('.bubble');
        if (bubble) { bubble.dataset.palette = String(palette); }
      });
    }
    save();
  }

  // Builds the reassignment menu fresh from the current speaker roster every
  // time it opens, rather than keeping a parallel copy in sync - a speaker
  // added or renamed after the page loaded is picked up automatically.
  //
  // scope, when passed, adds a second group above the speaker list: "This
  // sentence" / "This whole block" - the flat-card replacement for the old
  // cluster header's own reassignment control, which used to be the only
  // way to move a whole block of sentences to a different speaker at once
  // (see the review plan's "flat sentence cards" section, "preserve
  // turn-level reassignment"). Only a BUBBLE's own trigger passes this - a
  // menu with no scope group (scope === undefined) picks the speaker alone,
  // which is not reachable any more from ordinary bindMenus() clicks now
  // that the cluster header itself is gone, but keeps this function honest
  // about what it builds rather than hard-coding the group into every menu.
  // {current: 'line'|'block'} names which of the two is checked; the caller
  // (bindMenus()) is what remembers this across repeated opens of the same
  // menu instance, not this function - see its own scopeFor()/currentScope.
  function buildSpeakerMenu(fileIndex, currentId, scope) {
    var menu = el('div', 'spk-menu', { role: 'menu', 'aria-label': t('reassign', 'Reassign to') });

    if (scope) {
      var group = el('div', 'spk-menu-scope', { role: 'group', 'aria-label': t('reassign_scope', 'Apply to') });
      [
        ['line', t('reassign_scope_line', 'This sentence')],
        ['block', t('reassign_scope_block', 'This whole block')],
      ].forEach(function (pair) {
        var item = el('button', 'spk-scope-item', {
          role: 'menuitemradio',
          'aria-checked': String(pair[0] === scope.current),
        });
        item.type = 'button';
        item.dataset.scope = pair[0];
        item.textContent = pair[1];
        group.appendChild(item);
      });
      menu.appendChild(group);
    }

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

  // The .bubble currently raised above its siblings because it holds an
  // open .spk-menu - see .bubble.menu-open in 52-bubble.css for why this
  // has to be an explicit class transcript.js owns, rather than a :hover
  // rule: the menu stays open after the pointer leaves the card, so a
  // hover-keyed z-index would drop the card back underneath its next
  // sibling at exactly the moment the menu is being used, not before. Used
  // to be the whole .turn cluster - now that cards are flat, one sentence
  // wide, the card that needs raising is the .bubble the menu actually
  // opened from, not its (invisible) .turn wrapper.
  var menuOpenCard = null;

  // Which scope ('line' or 'block') is currently selected in the open
  // .spk-menu's own scope group (see buildSpeakerMenu()'s own comment) -
  // reset to 'line' every time a menu opens, and flipped in place by a
  // click on a .spk-scope-item without closing the menu, so a reader can
  // change their mind about scope before picking a speaker.
  var openMenuScope = 'line';

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
    if (menuOpenCard) { menuOpenCard.classList.remove('menu-open'); menuOpenCard = null; }
    openMenuBtn = null;
    openMenuScope = 'line';
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
        // Raises the .bubble the menu opened from, not the .turn it lives
        // in - see menuOpenCard's own comment for why a flat card is what
        // needs the stacking help now.
        menuOpenCard = btn.closest('.bubble');
        if (menuOpenCard) { menuOpenCard.classList.add('menu-open'); }
      }
    }
    btn.setAttribute('aria-expanded', 'true');
    openMenuBtn = btn;
    var first = menu.querySelector('[role="menuitemradio"]');
    if (first) { first.focus(); }
  }

  // Repaints every bubble in a block that is NOT itself carrying its own
  // per-sentence override, to the block's new speaker - the "apply to this
  // whole block" scope of the reassignment menu (see buildSpeakerMenu()'s
  // own comment), and the direct replacement for the old cluster header's
  // .spk, which used to be the only control that could move a whole block
  // at once. A bubble that already disagrees with its block (data-override)
  // is left alone: reassigning the block is not the same action as
  // clearing every sentence's own opinion about it, the same way the old
  // cluster-level reassignment never touched state.assignLine either.
  // Shared by reassignTurn() (a fresh choice) and applyAssignments()
  // (replaying a saved one on reload) - both need every non-overridden
  // bubble in the block to show the SAME new identity a live reassignment
  // paints, since a bubble's chip is the resting identity now, not an
  // override-only control (see _render_bubble_html()'s docstring).
  function repaintBlockBubbles(turn, newId, newPalette, fallback) {
    turn.querySelectorAll('.body .bubble').forEach(function (bubble) {
      if (bubble.hasAttribute('data-override')) { return; }
      bubble.dataset.speaker = newId;
      bubble.dataset.palette = newPalette;
      var btn = bubble.querySelector('.bubble-spk');
      if (btn) {
        btn.dataset.speaker = newId;
        btn.dataset.palette = newPalette;
        btn.dataset.fallback = fallback;
      }
    });
  }

  function reassignTurn(turn, newId, newPalette) {
    var section = turn.closest('.source');
    var fileIndex = section.dataset.file;
    var strip = stripFor(fileIndex);
    var row = strip && strip.querySelector('.speaker-row[data-speaker="' + newId + '"]');
    var fallback = row ? row.querySelector('.speaker-name').placeholder : '';

    turn.dataset.speaker = newId;
    turn.dataset.palette = newPalette;
    repaintBlockBubbles(turn, newId, newPalette, fallback);

    state.assign[turn.dataset.turn] = Number(newId);
    // applyNames repaints every .bubble-spk in the file from
    // state.names/fallback, which already covers every card in this block
    // now that each one's own data-speaker points at the new identity - no
    // separate "set this one label" path needed.
    applyNames(fileIndex);
    rebuildPlain(section);
    save();
  }

  // Paints (or clears) one bubble's own speaker chip. `newId` is the
  // override's speaker id, or null/undefined to clear the override.
  //
  // Clearing restores the BLOCK's own current identity onto the chip -
  // never blanks it - because every bubble's chip is the resting speaker
  // identity now, not an override-only affordance the way it was before
  // the cluster header existed (see _render_bubble_html()'s docstring): a
  // blank chip is not a valid state for a card to be in any more.
  //
  // Deliberately does not set the button's own label text itself:
  // applyNames() already repaints every .bubble-spk label in the file from
  // state.names/fallback (see its own comment), so duplicating that
  // name-resolution logic here would just be a second copy that could drift
  // from the first the next time a name changes. Every caller of this
  // function calls applyNames(fileIndex) afterwards.
  function paintBubbleOverride(bubble, fileIndex, newId) {
    var btn = bubble.querySelector('.bubble-spk');
    if (!btn) { return; }

    var id;
    if (newId === null || typeof newId === 'undefined') {
      bubble.removeAttribute('data-override');
      var turn = bubble.closest('.turn');
      id = turn ? turn.dataset.speaker : undefined;
      if (typeof id === 'undefined') { return; }
    } else {
      id = String(newId);
      // data-override on the bubble itself (not just on its button) is what
      // 52-bubble.css keys the disagreement's visual accent on. data-palette
      // rides on the bubble too, alongside the button's own copy, because
      // that CSS reads --spk/--spk-text off the bubble's own [data-palette]
      // (see 00-tokens.css's shared block).
      bubble.setAttribute('data-override', 'true');
    }

    var strip = stripFor(fileIndex);
    var row = strip && strip.querySelector('.speaker-row[data-speaker="' + id + '"]');
    var palette = row ? row.dataset.palette : id;
    var fallback = row ? row.querySelector('.speaker-name').placeholder : '';

    bubble.dataset.speaker = id;
    bubble.dataset.palette = String(palette);
    btn.dataset.speaker = id;
    btn.dataset.palette = String(palette);
    btn.dataset.fallback = fallback;
  }

  // Sets or clears a bubble's per-sentence override. Choosing the SAME
  // speaker the bubble's cluster already is clears the key rather than
  // storing a redundant entry equal to the cluster's own value - otherwise
  // state.assignLine would accumulate keys that mean nothing (see
  // hasLocalChanges() in js/08-storage.js, which would over-report unsaved
  // changes for an override that has no visible effect) and every reload
  // would keep replaying a no-op.
  function reassignLine(bubble, newId) {
    var turn = bubble.closest('.turn');
    var lineId = bubble.dataset.line;
    var fileIndex = turn.closest('.source').dataset.file;

    if (String(newId) === String(turn.dataset.speaker)) {
      delete state.assignLine[lineId];
      paintBubbleOverride(bubble, fileIndex, null);
    } else {
      state.assignLine[lineId] = Number(newId);
      paintBubbleOverride(bubble, fileIndex, newId);
    }
    // Repaints this bubble's own label (from state.names/fallback, same as
    // any other .bubble-spk - see applyNames()'s own comment) and keeps the
    // plain-text panel's headings/per-line tags in step, since an override
    // changes what rowSpeakerName() (js/32-plain-text.js) reads for this
    // turn.
    applyNames(fileIndex);
    save();
  }

  // Replays per-bubble speaker overrides saved in a previous session -
  // applyAssignments()'s sentence-level sibling. Must run AFTER
  // applyAssignments() (see 99-init.js): an override is only meaningful
  // relative to whichever speaker its cluster currently is (picking the
  // cluster's own speaker is what clears it - see reassignLine() above), so
  // the cluster's own replay has to be settled first.
  function applyLineAssignments() {
    Object.keys(state.assignLine).forEach(function (lineId) {
      var bubble = document.querySelector('.bubble[data-line="' + lineId + '"]');
      if (!bubble) { return; }
      var turn = bubble.closest('.turn');
      if (!turn) { return; }
      var fileIndex = turn.closest('.source').dataset.file;
      paintBubbleOverride(bubble, fileIndex, Number(state.assignLine[lineId]));
    });
  }

  // Delegated, not bound per-button: a bubble's own .bubble-spk and a
  // speaker row's .swatch-trigger, plus the popovers either one opens, are
  // handled by this one listener - added speakers get the same behaviour as
  // rendered ones for free, with nothing new to bind when a row is created
  // later. There is no more cluster-level .spk to bind at all - the header
  // that used to carry one is gone (see the review plan's "flat sentence
  // cards" section); the "apply to this whole block" scope option on the
  // bubble's own menu (see buildSpeakerMenu()) is what replaced it.
  function bindMenus() {
    document.addEventListener('click', function (e) {
      // The scope group's own item - flips openMenuScope in place without
      // closing the menu, and repaints the group's aria-checked state so a
      // reader can see which scope is selected before picking a speaker.
      var scopeItem = e.target.closest ? e.target.closest('.spk-scope-item') : null;
      if (scopeItem) {
        e.stopPropagation();
        openMenuScope = scopeItem.dataset.scope;
        var group = scopeItem.closest('.spk-menu-scope');
        if (group) {
          group.querySelectorAll('.spk-scope-item').forEach(function (item) {
            item.setAttribute('aria-checked', String(item === scopeItem));
          });
        }
        return;
      }

      // The bubble's own trigger - the only place a reassignment menu opens
      // from now. `current` prefers the button's OWN data-speaker, which is
      // always populated (the resting identity, not an override-only
      // value any more - see _render_bubble_html()'s docstring), so the
      // menu opens with whichever radio is actually in effect checked.
      var bubbleSpkBtn = e.target.closest ? e.target.closest('.bubble-spk') : null;
      if (bubbleSpkBtn) {
        e.stopPropagation();
        toggleMenu(bubbleSpkBtn, function () {
          var turn = bubbleSpkBtn.closest('.turn');
          var fileIndex = turn.closest('.source').dataset.file;
          var current = bubbleSpkBtn.dataset.speaker || turn.dataset.speaker;
          openMenuScope = 'line';
          return buildSpeakerMenu(fileIndex, current, { current: openMenuScope });
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
        // openMenuBtn - the button that opened this menu - still identifies
        // which bubble it belongs to, read before closeMenu() clears it
        // (same "read before closeMenu()" pattern the swatch branch below
        // already uses for its own row lookup).
        var lineBubble = openMenuBtn && openMenuBtn.classList.contains('bubble-spk')
          ? openMenuBtn.closest('.bubble') : null;
        var scope = openMenuScope;
        closeMenu();
        if (lineBubble && scope === 'block' && turn) {
          reassignTurn(turn, item.dataset.speaker, item.dataset.palette);
        } else if (lineBubble) {
          reassignLine(lineBubble, item.dataset.speaker);
        } else if (turn) {
          reassignTurn(turn, item.dataset.speaker, item.dataset.palette);
        }
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

  // Replays turn (block-level) reassignments saved in a previous session.
  function applyAssignments() {
    Object.keys(state.assign).forEach(function (turnId) {
      var turn = document.querySelector('.turn[data-turn="' + turnId + '"]');
      if (!turn) { return; }
      var newId = String(state.assign[turnId]);
      var section = turn.closest('.source');
      var strip = stripFor(section.dataset.file);
      var row = strip && strip.querySelector('.speaker-row[data-speaker="' + newId + '"]');
      var palette = row ? row.dataset.palette : newId;
      var fallback = row ? row.querySelector('.speaker-name').placeholder : '';

      turn.dataset.speaker = newId;
      turn.dataset.palette = palette;
      repaintBlockBubbles(turn, newId, palette, fallback);
    });
  }
