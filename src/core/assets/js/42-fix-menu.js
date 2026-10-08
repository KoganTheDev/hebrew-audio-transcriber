
  // Click-to-fix: clicking (or Enter/Space on) an uncertain word opens a menu
  // with the terms from the user's list it may have been (core's
  // annotate_suggestions), the word the model wrote if the app replaced it,
  // a field for any other word, and "keep as is". Each choice is a pick in
  // state.picks, rendered by renderTurn() in js/40-low-confidence.js.
  //
  // A pick is NOT an edit. Typing marks a card edited and drops all of its
  // shading (js/16-edits.js); picking one word must leave the card's other
  // uncertain words highlighted, so picks live in their own bucket and the
  // card is never marked edited by them.

  var fixMenu = null;
  var fixAnchor = null;
  // Opening can scroll the page (placeFixMenu); for a moment after an open
  // or a pick, follow() will not close the menu even if the word is briefly
  // measured off screen mid-scroll.
  var fixOpenedAt = 0;

  // Read off the page's own icon sprite rather than written out: the page has
  // to contain no URL at all (TestRenderHtml's offline guarantee), and the
  // SVG namespace is one.
  var SVG_NS = (document.querySelector('svg') || {}).namespaceURI;

  // The page's own sprite, exactly as _icon() in core/formatting/chrome.py
  // renders it - never a typed glyph, which falls back to whatever font the
  // browser finds.
  function spriteIcon(name) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS(SVG_NS, 'use');
    use.setAttribute('href', '#i-' + name);
    svg.appendChild(use);
    return svg;
  }

  function entryFor(span) {
    var turn = span.closest('.turn');
    var key = span.dataset.orig + '#' + span.dataset.occ;
    return turn ? lowEntries(turn.dataset.turn)[key] : null;
  }

  function fixItem(label, className, onPick, keyHint, iconName) {
    var item = el('button', 'fix-item' + (className ? ' ' + className : ''), {
      type: 'button',
      role: 'menuitem',
    });
    if (iconName) { item.appendChild(spriteIcon(iconName)); }
    var text = el('span');
    text.textContent = label;
    item.appendChild(text);
    if (keyHint) {
      var cap = el('kbd', 'fix-key', { 'aria-hidden': 'true' });
      cap.textContent = keyHint;
      item.appendChild(cap);
      item.setAttribute('aria-keyshortcuts', keyHint);
    }
    item.addEventListener('click', function (e) { e.stopPropagation(); onPick(); });
    return item;
  }

  // Punctuation around the word the reader is replacing ("שרן," "(שרן)"),
  // kept on a word they type that has none of its own.
  function keepPunctuation(original, typed) {
    var edge = /^([^\p{L}\p{N}]*)[\s\S]*?([^\p{L}\p{N}]*)$/u;
    if (/^[\p{L}\p{N}]/u.test(typed) === false || /[\p{L}\p{N}]$/u.test(typed) === false) {
      return typed;
    }
    var m = original.match(edge);
    return m ? m[1] + typed + m[2] : typed;
  }

  function buildFixMenu(span, entry) {
    var menu = el('div', 'fix-menu', { role: 'menu', 'aria-label': t('fix_menu', 'Fix this word') });
    menu.setAttribute('dir', getComputedStyle(span).direction === 'rtl' ? 'rtl' : 'ltr');

    var head = el('div', 'fix-head');
    var original = entry[4];
    if (original) {
      head.appendChild(document.createTextNode(t('fix_autofixed', 'Auto-corrected from') + ' '));
      var was = el('b', null, { dir: 'auto' });
      was.textContent = original;
      head.appendChild(was);
    } else {
      head.textContent = t('fix_unsure', 'The model was unsure') + ' · '
        + PLAIN_LRI + Math.round(entry[1] * 100) + '%' + PLAIN_PDI;
    }
    menu.appendChild(head);

    var suggestions = entry[3] || [];
    if (suggestions.length) {
      var label = el('div', 'fix-label');
      label.textContent = t('fix_terms', 'From your terms');
      menu.appendChild(label);
      suggestions.slice(0, 3).forEach(function (term, i) {
        menu.appendChild(fixItem(term, i === 0 ? 'fix-top' : '', function () {
          applyPick(span, term);
        }, String(i + 1)));
      });
    } else if (!original) {
      var none = el('div', 'fix-none');
      none.textContent = t('fix_none', 'No close term in your list.');
      menu.appendChild(none);
    }
    if (original) {
      menu.appendChild(fixItem(t('fix_restore', 'Restore original') + ': ' + original,
        'fix-restore', function () { applyPick(span, original); }, null, 'undo'));
    }

    menu.appendChild(el('div', 'fix-sep', { role: 'separator' }));
    var other = el('div', 'fix-other');
    other.appendChild(spriteIcon('edit'));
    var input = el('input', null, {
      type: 'text',
      placeholder: t('fix_other', 'Another word…'),
      'aria-label': t('fix_other', 'Another word…'),
    });
    input.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') { return; }
      e.preventDefault();
      var typed = input.value.trim();
      if (typed) { applyPick(span, keepPunctuation(span.textContent, typed)); }
    });
    other.appendChild(input);
    menu.appendChild(other);

    menu.appendChild(fixItem(t('fix_keep', 'Keep as is'), 'fix-quiet', function () {
      applyPick(span, null);
    }, null, 'check'));
    return menu;
  }

  function openFixMenu(span) {
    var entry = entryFor(span);
    if (!entry) { return; }
    closeFixMenu(false);
    // One popover at a time, whichever kind.
    if (typeof closeMenu === 'function') { closeMenu(); }

    fixAnchor = span;
    fixOpenedAt = Date.now();
    span.classList.add('fix-open');
    span.setAttribute('aria-expanded', 'true');
    fixMenu = buildFixMenu(span, entry);
    document.body.appendChild(fixMenu);
    placeFixMenu(span);
    var first = fixMenu.querySelector('.fix-item, input');
    if (first) { first.focus({ preventScroll: true }); }
  }

  function closeFixMenu(refocus) {
    if (!fixMenu) { return; }
    fixMenu.remove();
    fixMenu = null;
    document.body.style.paddingBottom = '';
    if (fixAnchor) {
      fixAnchor.classList.remove('fix-open');
      fixAnchor.setAttribute('aria-expanded', 'false');
      if (refocus && fixAnchor.isConnected) { fixAnchor.focus(); }
    }
    fixAnchor = null;
  }

  // Always below the word, start edges aligned - never flipped above it, so
  // the menu is where the eye already is. A word too low for the menu to fit
  // scrolls the page up just enough; near the end of the transcript, where
  // there is no page left to scroll, the page is lent the missing room for as
  // long as the menu is open (closeFixMenu takes it back). Fixed, physical
  // left/top from the word's rect, for positionDetachedMenu()'s reasons.
  function placeFixMenu(span, follow) {
    var menuRect = fixMenu.getBoundingClientRect();
    var rect = span.getBoundingClientRect();
    var overflow = rect.bottom + 6 + menuRect.height - (window.innerHeight - 8);
    if (overflow > 0 && !follow) {
      var doc = document.scrollingElement || document.documentElement;
      var room = doc.scrollHeight - window.innerHeight - window.scrollY;
      if (room < overflow) {
        document.body.style.paddingBottom = (overflow - room + 8) + 'px';
      }
      fixOpenedAt = Date.now();
      window.scrollBy(0, overflow);
      rect = span.getBoundingClientRect();
    }
    var width = document.documentElement.clientWidth;
    var rtl = fixMenu.getAttribute('dir') === 'rtl';
    var left = rtl ? rect.right - menuRect.width : rect.left;
    left = Math.max(8, Math.min(left, width - menuRect.width - 8));
    fixMenu.style.top = (rect.bottom + 6) + 'px';
    fixMenu.style.left = left + 'px';
  }

  function applyPick(span, value) {
    var turn = span.closest('.turn');
    if (!turn) { return; }
    var turnId = turn.dataset.turn;
    var key = span.dataset.orig + '#' + span.dataset.occ;
    state.picks = state.picks || {};
    state.picks[turnId] = state.picks[turnId] || {};
    state.picks[turnId][key] = value;

    // The uncertain word after this one in reading order, captured before the
    // re-render replaces every span in the card - so a keyboard reader can
    // work down the transcript without reaching for the mouse.
    var all = Array.prototype.slice.call(document.querySelectorAll('.lowconf'));
    var nextIndex = all.indexOf(span) + 1;

    closeFixMenu(false);
    fixOpenedAt = Date.now();
    renderTurn(turn);
    if (typeof value === 'string') {
      turn.querySelectorAll('.picked').forEach(function (picked) {
        if (picked.dataset.orig === span.dataset.orig && picked.textContent === value) {
          picked.classList.add('just-picked');
        }
      });
    }
    schedulePlain(turn.closest('.source'));
    save();

    var next = document.querySelectorAll('.lowconf')[nextIndex - 1];
    if (document.documentElement.hasAttribute('data-kbd') && next) {
      next.focus();
    }
  }

  function moveFixFocus(step) {
    var stops = Array.prototype.slice.call(fixMenu.querySelectorAll('.fix-item, input'));
    var at = stops.indexOf(document.activeElement);
    var next = stops[(at + step + stops.length) % stops.length];
    if (next) { next.focus(); }
  }

  function bindFixMenu() {
    // Before the click, so the editable card never places a caret in the word.
    document.addEventListener('mousedown', function (e) {
      if (e.target.closest && e.target.closest('.lowconf')) { e.preventDefault(); }
    }, true);

    document.addEventListener('click', function (e) {
      var span = e.target.closest ? e.target.closest('.lowconf') : null;
      if (span) {
        e.preventDefault();
        if (span === fixAnchor) { closeFixMenu(true); } else { openFixMenu(span); }
        return;
      }
      if (fixMenu && !fixMenu.contains(e.target)) { closeFixMenu(false); }
    });

    document.addEventListener('keydown', function (e) {
      var span = e.target.closest ? e.target.closest('.lowconf') : null;
      if (span && !fixMenu && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        openFixMenu(span);
        return;
      }
      if (!fixMenu) { return; }
      if (e.key === 'Escape') {
        // Capture-phase listeners elsewhere (help, tour) close their own
        // layers on Escape; this one is the menu's.
        e.stopPropagation();
        closeFixMenu(true);
        return;
      }
      var inField = e.target.tagName === 'INPUT';
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        moveFixFocus(e.key === 'ArrowDown' ? 1 : -1);
        return;
      }
      if (!inField && /^[1-3]$/.test(e.key)) {
        var shortcut = fixMenu.querySelector('[aria-keyshortcuts="' + e.key + '"]');
        if (shortcut) { e.preventDefault(); shortcut.click(); }
      }
    }, true);

    // The menu follows its word instead of closing. Closing on resize lost a
    // half-typed word on a phone, where focusing the field opens the
    // on-screen keyboard and the keyboard resizes the page; closing on scroll
    // lost it when the browser scrolled that field into view. It closes only
    // once the word itself has left the screen.
    function follow() {
      if (!fixMenu || !fixAnchor) { return; }
      var rect = fixAnchor.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight) {
        if (Date.now() - fixOpenedAt > 400) { closeFixMenu(false); }
        return;
      }
      placeFixMenu(fixAnchor, true);
    }
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', follow);
  }
