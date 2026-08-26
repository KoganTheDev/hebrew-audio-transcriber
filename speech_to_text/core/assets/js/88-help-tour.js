  // ------------------------------------------------------------- help & tour

  // Shared by the help panel and the tour's caption card: both are modal
  // overlays that have to keep Tab cycling inside themselves rather than
  // leaking focus out to the page underneath. Queried live rather than
  // cached, because the help panel's content is static but the tour card's
  // Back button toggles [hidden] on and off as the step index moves, which
  // would silently go stale in a cached list.
  function focusableIn(container) {
    var all = container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.prototype.filter.call(all, function (el) {
      // offsetParent is null for both `display: none` and a [hidden]
      // ancestor - either way, an element a reader cannot see must not be
      // reachable by Tab either, or the cycle would silently include dead
      // stops.
      return !el.disabled && el.offsetParent !== null;
    });
  }

  function trapTabKey(e, container) {
    if (e.key !== 'Tab') { return; }
    var focusable = focusableIn(container);
    if (!focusable.length) { return; }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // The help panel: markup and content are entirely server-rendered (see
  // _render_help_html() in core/formatting) - this only ever toggles
  // [hidden] and aria-expanded, and manages focus. Never reaches into
  // `state` or calls save(): the panel is pure reference material, and
  // opening or closing it must be invisible to hasLocalChanges().
  function bindHelp() {
    var btn = document.getElementById('help');
    var panel = document.getElementById('help-panel');
    var closeBtn = document.getElementById('help-close');
    var tourBtn = document.getElementById('tour-start');
    if (!btn || !panel) { return; }

    // The element focus should return to on close - the toolbar button in
    // the ordinary case, but captured fresh on every open rather than
    // hardcoded to `btn` in case some future caller opens help by another
    // route (a keyboard shortcut, say) with a different element focused.
    var opener = null;

    function openHelp() {
      opener = document.activeElement;
      panel.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      if (closeBtn) { closeBtn.focus(); }
    }

    function closeHelp() {
      panel.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      if (opener && typeof opener.focus === 'function') { opener.focus(); }
      opener = null;
    }

    btn.addEventListener('click', openHelp);
    if (closeBtn) { closeBtn.addEventListener('click', closeHelp); }

    // .help-panel is the full-viewport flex container that centres
    // .help-sheet inside it - a click anywhere in that container that is
    // NOT on the sheet (or one of the sheet's own children, which never
    // bubble past it without being handled first) is a click on the scrim
    // itself, i.e. e.target === panel exactly.
    panel.addEventListener('click', function (e) {
      if (e.target === panel) { closeHelp(); }
    });

    panel.addEventListener('keydown', function (e) {
      if (panel.hidden) { return; }
      if (e.key === 'Escape') { closeHelp(); return; }
      trapTabKey(e, panel);
    });

    if (tourBtn) {
      tourBtn.addEventListener('click', function () {
        closeHelp();
        startTour();
      });
    }
  }

  // (selector, find) - `selector` documents which markup this step points
  // at (and is what tests assert against); `find` is how the step is
  // actually located, since one step (the speaker roster) needs more than a
  // plain querySelector - see its own comment below. Every other step's
  // `find` is just document.querySelector(selector).
  //
  // Order matters: it is the order steps are walked in, and it deliberately
  // matches the page's own top-to-bottom reading order (toolbar/file
  // context first, then the sidebar, then the reading column's own
  // affordances in the order a reader meets them), the same choice
  // _render_help_html() documents for the help panel's own entry order.
  var TOUR_STEPS = [
    {
      selector: '.file-bar',
      titleKey: 'tour_file_title', titleFallback: 'This recording',
      bodyKey: 'tour_file_body',
      bodyFallback: "This bar stays on screen and names the file you're "
        + 'reading - in a batch, it also shows its position among the others.',
    },
    {
      selector: '.outline',
      titleKey: 'tour_outline_title', titleFallback: 'Files and speakers',
      bodyKey: 'tour_outline_body',
      bodyFallback: 'This sidebar lists every file in the batch and, for '
        + 'each one, the speakers detected inside it. Click a filename to '
        + 'jump straight to it.',
    },
    {
      selector: '.tb-search',
      titleKey: 'tour_search_title', titleFallback: 'Search',
      bodyKey: 'tour_search_body',
      bodyFallback: 'Type here to search every turn in this recording. The '
        + 'chevrons - or Enter and Shift+Enter - jump to the next or '
        + 'previous match.',
    },
    {
      // Every file in the batch renders its own .speakers strip, but only
      // one is visible at a time once .outline.js-ready is present (see
      // bindOutline() and the .outline.js-ready .speakers:not(.active) rule
      // in the stylesheet (core/assets/css/)) - a plain document.querySelector('.speakers')
      // would always land on file 0's strip regardless of which file the
      // reader is actually looking at, including mid-tour if a reader
      // scrolled before opening help. .active is preferred; falling back to
      // the first .speakers covers the (script-disabled-at-render-time,
      // impossible in practice once this file is running, but cheap to
      // guard) case where nothing has been marked active yet.
      selector: '.speakers',
      find: function () {
        return document.querySelector('.speakers.active') || document.querySelector('.speakers');
      },
      titleKey: 'tour_speakers_title', titleFallback: 'Speaker names and colours',
      bodyKey: 'tour_speakers_body',
      bodyFallback: 'Rename a speaker here, or recolour them from the '
        + "swatch beside their name. Clicking a sentence's own speaker "
        + 'chip reassigns just that sentence, or the whole block around '
        + 'it, to someone else.',
    },
    {
      selector: '.turn .ts',
      titleKey: 'tour_playback_title', titleFallback: 'Play a moment',
      bodyKey: 'tour_playback_body',
      bodyFallback: "Click a sentence's own timestamp to play the "
        + 'recording from there - a small player appears, and stops again '
        + "at the sentence's own end.",
    },
    {
      selector: '.turn .body[contenteditable]',
      titleKey: 'tour_editing_title', titleFallback: 'Editing the transcript',
      bodyKey: 'tour_editing_body',
      bodyFallback: "Click into any turn's text to correct it directly. "
        + 'Changes save automatically to this browser as you type.',
    },
    {
      selector: '#toggle-flags',
      titleKey: 'tour_flags_title', titleFallback: 'Show uncertain words',
      bodyKey: 'tour_flags_body',
      bodyFallback: 'This button highlights the words the model itself '
        + "was least sure about, so you know what's worth a second look.",
    },
    {
      selector: '#export',
      titleKey: 'tour_export_title', titleFallback: 'Save a copy',
      bodyKey: 'tour_export_body',
      bodyFallback: 'This page can only save your edits to this browser '
        + 'automatically. "Save a copy" is what actually writes them into '
        + 'a real file you can keep or share.',
    },
  ];

  // Everything the running tour needs to clean itself up - a single object
  // rather than a scatter of module-level variables, so endTour() has one
  // thing to null out and cannot half-forget a piece of it. null whenever no
  // tour is running, which doubles as the re-entrancy guard in startTour().
  var tour = null;

  // Resolved fresh every time the tour starts, never cached across a
  // render: which selectors match depends on what this particular document
  // actually contains (a single file has no .outline; a document rendered
  // without timestamps has no .ts; a document with one detected speaker has
  // no .speakers strip at all - see _render_outline_html()'s own docstring
  // for the conditions). A step whose target is missing is dropped
  // silently, and the n/total counter is built from what is LEFT, not from
  // TOUR_STEPS.length - a hardcoded 8 would immediately be wrong on the
  // first document that omits anything.
  function resolveTourSteps() {
    var resolved = [];
    TOUR_STEPS.forEach(function (step) {
      var el = step.find ? step.find() : document.querySelector(step.selector);
      if (el) { resolved.push({ def: step, el: el }); }
    });
    return resolved;
  }

  function buildTourChrome() {
    var scrim = el('div', 'tour-scrim', { 'aria-hidden': 'true' });
    var ring = el('div', 'tour-ring', { 'aria-hidden': 'true' });

    var card = el('div', 'tour-card', {
      id: 'tour-card',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'tour-title',
      // Not part of the normal Tab order (that is what the trap is for) -
      // this is only so card.focus() below can move the accessibility
      // focus onto the dialog itself when a step changes, the same "focus
      // the container, let its aria-labelledby announce the new content"
      // pattern any dialog that swaps its own content on the fly needs.
      tabindex: '-1',
    });

    var count = el('p', 'tour-count');
    // Same bidi shape as .file-position and format_range()'s
    // "M:SS - M:SS" (see the LRI/PDI comment block in
    // core/formatting): a neutral "/" sitting between two LTR
    // digit runs inside an RTL paragraph. Without the isolate
    // renderTourStep() wraps this in, step one of eight rendered as
    // "8 / 1" - the slash resolved RTL and swapped which number read
    // as the position and which read as the total, the exact bug
    // .file-position already carries a guard against. dir="ltr" is
    // not sufficient alone: this is a flow child of an RTL card, so
    // the isolate is what stops the surrounding direction reaching
    // into the digit runs in the first place.
    count.setAttribute('dir', 'ltr');
    var title = el('h2', 'tour-title', { id: 'tour-title' });
    var body = el('p', 'tour-body');

    var actions = el('div', 'tour-actions');

    var skipBtn = el('button', 'tb-btn tour-skip');
    skipBtn.type = 'button';
    var backBtn = el('button', 'tb-btn tour-back');
    backBtn.type = 'button';
    var nextBtn = el('button', 'tb-btn primary tour-next');
    nextBtn.type = 'button';

    actions.appendChild(skipBtn);
    actions.appendChild(backBtn);
    actions.appendChild(nextBtn);
    card.appendChild(count);
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(actions);

    return {
      scrim: scrim, ring: ring, card: card,
      count: count, title: title, body: body,
      skipBtn: skipBtn, backBtn: backBtn, nextBtn: nextBtn,
    };
  }

  // Re-measures the current step's target and repaints the ring and card
  // around it. Cheap enough (one getBoundingClientRect plus
  // positionDetachedMenu's own couple of reads) to run unthrottled from a
  // rAF callback rather than needing its own further debounce.
  function updateTourSpotlight() {
    if (!tour) { return; }
    var entry = tour.steps[tour.index];
    var rect = entry.el.getBoundingClientRect();
    var pad = 6;

    var ring = tour.chrome.ring;
    ring.style.top = (rect.top - pad) + 'px';
    ring.style.left = (rect.left - pad) + 'px';
    ring.style.width = (rect.width + pad * 2) + 'px';
    ring.style.height = (rect.height + pad * 2) + 'px';

    positionDetachedMenu(tour.chrome.card, entry.el);
  }

  function scheduleTourUpdate() {
    if (!tour || tour.raf) { return; }
    tour.raf = window.requestAnimationFrame(function () {
      if (!tour) { return; }
      tour.raf = null;
      updateTourSpotlight();
    });
  }

  function renderTourStep(index) {
    var entry = tour.steps[index];
    tour.index = index;
    var chrome = tour.chrome;
    var n = tour.steps.length;

    chrome.count.textContent = PLAIN_LRI
      + t('tour_step_position', '{i} / {n}')
        .replace('{i}', String(index + 1)).replace('{n}', String(n))
      + PLAIN_PDI;
    chrome.title.textContent = t(entry.def.titleKey, entry.def.titleFallback);
    chrome.body.textContent = t(entry.def.bodyKey, entry.def.bodyFallback);
    chrome.skipBtn.textContent = t('tour_skip', 'Skip');
    chrome.backBtn.textContent = t('tour_back', 'Back');
    chrome.nextBtn.textContent = (index === n - 1)
      ? t('tour_done', 'Done')
      : t('tour_next', 'Next');
    chrome.backBtn.hidden = index === 0;

    // Positioned once immediately, so the ring/card do not flash at (0, 0)
    // for a frame before the first scroll event lands - then left to the
    // scroll listener below to keep tracking the target as
    // scrollIntoView's own (possibly smooth, possibly instant per
    // scrollBehavior()) animation actually moves it.
    updateTourSpotlight();
    entry.el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });

    // Re-announces the step to a screen reader on every change (a dialog's
    // aria-labelledby is read out when the dialog itself receives focus),
    // and keeps Tab cycling inside a container that is guaranteed to still
    // exist even on the step where Back has just been hidden.
    chrome.card.focus();
  }

  function endTour() {
    if (!tour) { return; }
    var chrome = tour.chrome;
    if (tour.raf) { window.cancelAnimationFrame(tour.raf); }
    document.removeEventListener('keydown', tour.keydownHandler, true);
    window.removeEventListener('resize', tour.moveHandler);
    document.removeEventListener('scroll', tour.moveHandler, true);
    chrome.scrim.remove();
    chrome.ring.remove();
    chrome.card.remove();
    tour = null;

    // Always #help, per the tour's own accessibility contract - not
    // whichever element happened to be focused before the tour started,
    // which by construction is #help anyway (bindHelp()'s tour-start click
    // handler closes the help panel, which already returns focus to #help,
    // immediately before calling startTour()). Naming it explicitly here
    // rather than relying on that chain means this still does the right
    // thing if a future caller ever starts the tour some other way.
    var helpBtn = document.getElementById('help');
    if (helpBtn) { helpBtn.focus(); }
  }

  // Manual trigger only - bound to #tour-start's click in bindHelp(). No
  // auto-launch, no first-visit flag in `state`: a reader who has not asked
  // for the tour must never have it start itself, and nothing about running
  // it may touch localStorage (see the module docstring's autosave
  // contract) - the tour reads the DOM and getBoundingClientRect(), full
  // stop, and every handler below is careful never to call save() or reach
  // into `state`.
  function startTour() {
    var steps = resolveTourSteps();
    if (!steps.length) { return; }
    // Re-entrancy guard: starting the tour again while one is already
    // running (there is no UI path to do this today, since #tour-start only
    // exists inside the help panel the tour itself closes, but a future
    // second entry point should not be able to leak the first run's
    // overlay) tears the old one down cleanly first rather than stacking a
    // second scrim/ring/card on top of it.
    if (tour) { endTour(); }

    var chrome = buildTourChrome();
    document.body.appendChild(chrome.scrim);
    document.body.appendChild(chrome.ring);
    document.body.appendChild(chrome.card);

    tour = { steps: steps, index: 0, chrome: chrome, raf: null };

    chrome.skipBtn.addEventListener('click', endTour);
    chrome.backBtn.addEventListener('click', function () {
      if (tour && tour.index > 0) { renderTourStep(tour.index - 1); }
    });
    chrome.nextBtn.addEventListener('click', function () {
      if (!tour) { return; }
      if (tour.index < tour.steps.length - 1) {
        renderTourStep(tour.index + 1);
      } else {
        endTour();
      }
    });

    // Capture-phase, like closeMenu()'s own Escape handler and the
    // scroll-closes-the-swatch-menu listener above - the tour is modal, so
    // it has to see these keys before any other keydown listener on the
    // page gets a chance to react to them (bindChrome()'s own "/" focuses
    // search" handler, for one, would otherwise fire while the tour has the
    // page pinned behind its scrim).
    tour.keydownHandler = function (e) {
      if (e.key === 'Escape') { endTour(); return; }
      // Left/Right-as-next/back is a bonus, not the primary path (Tab to
      // the buttons and press them is) - kept intentionally simple, with no
      // attempt to flip the pair for RTL, since an arrow key's physical
      // direction on the keyboard is what a reader's hand actually knows,
      // independent of which way the text on screen flows.
      if (e.key === 'ArrowRight') { e.preventDefault(); chrome.nextBtn.click(); return; }
      if (e.key === 'ArrowLeft' && !chrome.backBtn.hidden) {
        e.preventDefault();
        chrome.backBtn.click();
        return;
      }
      trapTabKey(e, chrome.card);
    };
    document.addEventListener('keydown', tour.keydownHandler, true);

    // Same rAF-scheduled recompute drives both triggers - a resize and a
    // scroll (of the window, or of any scrollable ancestor, hence capture:
    // true, the same reasoning as closeMenu()'s own capture-phase scroll
    // listener above) are just two different reasons the target's rect
    // might have changed.
    tour.moveHandler = scheduleTourUpdate;
    window.addEventListener('resize', tour.moveHandler);
    document.addEventListener('scroll', tour.moveHandler, true);

    renderTourStep(0);
  }
