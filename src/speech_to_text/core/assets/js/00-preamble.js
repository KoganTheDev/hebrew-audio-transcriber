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
  // assignLine[lineId] = speaker id - the sentence-level counterpart to
  // assign above: a bubble's OWN override of its cluster's speaker, set
  // only when a single sentence has been reassigned away from whatever its
  // cluster currently is. Deliberately a separate bucket rather than reusing
  // assign with a "0-0-2" style key - the two are replayed in a fixed order
  // (cluster first, see applyLineAssignments() in js/24-speakers-menus.js)
  // and keeping them in separate objects makes that ordering dependency
  // obvious at the call site instead of hidden in a shared key shape.
  var state = {
    turns: {}, names: {}, flags: false, theme: null, opts: {},
    speakers: {}, assign: {}, assignLine: {},
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

  // Builds one DOM node with its class and attributes set in one call -
  // pulled out once the split into fragments made it obvious that four
  // separate builders (the swatch trigger, a speaker row, a menu item, the
  // tour's own chrome) were each hand-rolling the same
  // createElement/className/setAttribute ladder, about 90 lines of it in
  // total. `attrs` is applied via setAttribute rather than property
  // assignment so callers can set ARIA attributes (aria-haspopup,
  // role, ...) through the same call as everything else - a caller that
  // still needs a DOM property (dataset, textContent, event listeners) sets
  // it on the returned node itself, same as before this helper existed.
  function el(tag, className, attrs) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (attrs) {
      Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    }
    return node;
  }

  // The two selectors this file rebuilds by hand-concatenating a file index
  // more than any others - nine call sites between them before this pass.
  // Pulled out once, here, rather than left as nine copies of the same
  // string-concatenation-into-querySelector, so a future change to either
  // shape (say, switching to a data-file-id that isn't a bare integer) has
  // one place to make it.
  function stripFor(i) { return document.querySelector('.speakers[data-file="' + i + '"]'); }
  function sectionFor(i) { return document.querySelector('.source[data-file="' + i + '"]'); }

  // U+2066/U+2069 - see the LRI/PDI comment block in core/formatting.
  // Shared here, not left local to the plain-text section that originally
  // defined them, because the guided tour's step counter (see
  // renderTourStep() in the help & tour section) needs the exact same
  // isolate pair for its own "{i} / {n}" readout and used to reach across
  // into plain text's own section for them.
  var PLAIN_LRI = '⁦';
  var PLAIN_PDI = '⁩';
