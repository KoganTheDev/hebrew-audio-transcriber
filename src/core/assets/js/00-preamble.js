  var payloadEl = document.getElementById('transcript-data');
  if (!payloadEl) { return; }

  var DATA = JSON.parse(payloadEl.textContent);
  var STR = DATA.strings || {};
  var DOC_ID = document.documentElement.dataset.docId;
  var KEY = 'hebrew-transcript:' + DOC_ID;

  // speakers[fileIndex][id] = {fallback, palette, added}. `added` marks a
  // speaker with no server-rendered row, so applySpeakerState() rebuilds the
  // whole row; without it the row already exists and only needs repainting.
  // assign[turnId] = speaker id - cluster-level reassignments since render.
  // assignLine[lineId] = speaker id - one bubble's override of its cluster.
  // Kept in its own bucket rather than folded into assign so the fixed replay
  // order (cluster first, see applyLineAssignments() in
  // js/24-speakers-menus.js) stays visible at the call site.
  // picks[turnId]["<word>#<occurrence>"] = replacement, or null for "keep as
  // is" - the click-to-fix menu's choices (js/42-fix-menu.js), kept apart
  // from `turns` because a pick must not mark its card edited.
  // flags starts on: uncertain words are the point of reviewing a
  // transcript. A document whose reader turned highlighting off keeps it off,
  // because load() merges the saved state over these defaults.
  var state = {
    turns: {}, names: {}, flags: true, theme: null, opts: {},
    speakers: {}, assign: {}, assignLine: {}, picks: {},
  };
  var exported = true;
  var saveTimer = null;
  var statusEl = document.getElementById('status');

  function t(key, fallback) { return STR[key] || fallback || key; }

  // CSS scroll-behavior does not govern scrollIntoView's explicit option, so
  // reduced-motion has to be honoured here too.
  function scrollBehavior() {
    return window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 'auto' : 'smooth';
  }

  // `attrs` goes through setAttribute rather than property assignment so
  // callers can set ARIA attributes through the same call; DOM properties
  // (dataset, textContent, listeners) are still set on the returned node.
  function el(tag, className, attrs) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (attrs) {
      Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    }
    return node;
  }

  function stripFor(i) { return document.querySelector('.speakers[data-file="' + i + '"]'); }
  function sectionFor(i) { return document.querySelector('.source[data-file="' + i + '"]'); }

  // U+2066/U+2069 - see the LRI/PDI comment block in core/formatting. Shared
  // here because the guided tour's step counter needs the same isolate pair
  // for its "{i} / {n}" readout as the plain-text section does.
  var PLAIN_LRI = '⁦';
  var PLAIN_PDI = '⁩';
