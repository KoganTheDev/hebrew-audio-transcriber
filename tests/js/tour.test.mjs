// Behavioural coverage for the guided tour (startTour()/resolveTourSteps()/
// endTour() in transcript.js): stepping forward and back, Escape ending it,
// the step count adapting to what a render actually contains, and cleanup
// leaving no DOM or listeners behind.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function keydown(target, key) {
  target.dispatchEvent(new target.ownerDocument.defaultView.KeyboardEvent(
    'keydown', { key, bubbles: true, cancelable: true }
  ));
}

function startTour(document) {
  click(document.getElementById('help'));
  click(document.getElementById('tour-start'));
  return document.getElementById('tour-card');
}

test('the tour resolves all eight steps on a document with every affordance', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);

  const count = document.querySelector('.tour-count').textContent;
  // PLAIN_LRI/PLAIN_PDI bracket the digits (see renderTourStep()) - stripped
  // here since this test is about the count, not the bidi isolate (that is
  // test_step_counter_is_bidi_isolated's job, still checked at the source
  // level in tests/test_formatting.py).
  assert.equal(count.replace(/[⁦⁩]/g, ''), '1 / 8');

  window.close();
});

test('the tour drops to fewer steps on a document missing an outline, speakers and timestamps', () => {
  const { window, document } = buildWindow(getFixtureHtml('degenerate'));
  startTour(document);

  const count = document.querySelector('.tour-count').textContent.replace(/[⁦⁩]/g, '');
  assert.equal(count, '1 / 5', 'expected the file bar, search, editing, flags and export steps only');

  window.close();
});

test('Next advances the step and updates the counter and title', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);

  const firstTitle = document.querySelector('.tour-title').textContent;
  click(document.querySelector('.tour-next'));

  const count = document.querySelector('.tour-count').textContent.replace(/[⁦⁩]/g, '');
  assert.equal(count, '2 / 8');
  assert.notEqual(document.querySelector('.tour-title').textContent, firstTitle);

  window.close();
});

test('Back is hidden on the first step and moves to the previous step otherwise', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);

  const back = document.querySelector('.tour-back');
  assert.equal(back.hidden, true, 'Back must be hidden on step one');

  click(document.querySelector('.tour-next'));
  assert.equal(back.hidden, false);

  click(back);
  const count = document.querySelector('.tour-count').textContent.replace(/[⁦⁩]/g, '');
  assert.equal(count, '1 / 8');
  assert.equal(back.hidden, true);

  window.close();
});

test('Next on the last step ends the tour instead of stepping past it', () => {
  const { window, document } = buildWindow(getFixtureHtml('degenerate'));
  startTour(document);

  for (let i = 0; i < 4; i++) { click(document.querySelector('.tour-next')); }
  assert.ok(document.querySelector('.tour-card'), 'tour should still be running with one step left');

  click(document.querySelector('.tour-next'));
  assert.equal(document.querySelector('.tour-card'), null, 'the final Next must end the tour, not overshoot');

  window.close();
});

test('Escape ends the tour and returns focus to the help button', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const card = startTour(document);

  keydown(card, 'Escape');

  assert.equal(document.querySelector('.tour-card'), null);
  assert.equal(document.querySelector('.tour-scrim'), null);
  assert.equal(document.querySelector('.tour-ring'), null);
  assert.equal(document.activeElement, document.getElementById('help'));

  window.close();
});

test('Skip ends the tour immediately from any step', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);
  click(document.querySelector('.tour-next'));

  click(document.querySelector('.tour-skip'));

  assert.equal(document.querySelector('.tour-card'), null);

  window.close();
});

test('ending the tour removes every element it created and every listener it added', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const addedKeydown = [];
  const removedKeydown = [];
  const addedResize = [];
  const removedResize = [];
  const addedScroll = [];
  const removedScroll = [];
  const origDocAdd = document.addEventListener.bind(document);
  const origDocRemove = document.removeEventListener.bind(document);
  const origWinAdd = window.addEventListener.bind(window);
  const origWinRemove = window.removeEventListener.bind(window);
  document.addEventListener = (type, fn, opts) => {
    if (type === 'keydown') addedKeydown.push(fn);
    if (type === 'scroll') addedScroll.push(fn);
    return origDocAdd(type, fn, opts);
  };
  document.removeEventListener = (type, fn, opts) => {
    if (type === 'keydown') removedKeydown.push(fn);
    if (type === 'scroll') removedScroll.push(fn);
    return origDocRemove(type, fn, opts);
  };
  window.addEventListener = (type, fn, opts) => {
    if (type === 'resize') addedResize.push(fn);
    return origWinAdd(type, fn, opts);
  };
  window.removeEventListener = (type, fn, opts) => {
    if (type === 'resize') removedResize.push(fn);
    return origWinRemove(type, fn, opts);
  };

  startTour(document);
  click(document.querySelector('.tour-skip'));

  assert.equal(document.querySelector('.tour-card'), null);
  assert.equal(document.querySelector('.tour-scrim'), null);
  assert.equal(document.querySelector('.tour-ring'), null);
  assert.ok(addedResize.length >= 1, 'expected the tour to have added a resize listener');
  assert.ok(addedScroll.length >= 1, 'expected the tour to have added a scroll listener');
  for (const fn of addedResize) assert.ok(removedResize.includes(fn), 'resize listener leaked');
  for (const fn of addedScroll) assert.ok(removedScroll.includes(fn), 'scroll listener leaked');
  // The tour's own capture-phase keydown handler must be removed; this does
  // not assert every keydown listener ever added on document is gone (help
  // and the menus add their own, permanent ones), only that whichever one(s)
  // the tour itself added during this run were also removed.
  const tourAdded = addedKeydown.filter((fn) => !removedKeydown.includes(fn));
  assert.equal(tourAdded.length, 0, 'the tour keydown handler leaked past endTour()');

  window.close();
});

test('the tour never touches saved edit state', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  assert.equal(window.localStorage.getItem(key), null);

  startTour(document);
  click(document.querySelector('.tour-next'));
  click(document.querySelector('.tour-next'));
  click(document.querySelector('.tour-back'));
  click(document.querySelector('.tour-skip'));

  assert.equal(window.localStorage.getItem(key), null, 'the tour must never write to localStorage');

  window.close();
});

// ---------------------------------------------------------------------
// The tests below replace what used to be source-text greps in
// tests/test_formatting.py's TestGuidedTour and TestHelpPanelWiring
// classes (checking exact strings like "document.querySelector('.speakers
// .active')" or a hardcoded STEP_SELECTORS list existed verbatim in
// transcript.js). Each one now proves the same claim by actually driving
// the tour and reading the result.

function withRoutedRect(window, router, fn) {
  const proto = window.Element.prototype;
  const original = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () {
    const routed = router(this);
    return routed || original.call(this);
  };
  try {
    return fn();
  } finally {
    proto.getBoundingClientRect = original;
  }
}

function rect(box) {
  return {
    top: box.top, left: box.left, right: box.right, bottom: box.bottom,
    width: box.width, height: box.height, x: box.left, y: box.top,
    toJSON() { return this; },
  };
}

function titleSequence(document) {
  const titles = [document.querySelector('.tour-title').textContent];
  while (!document.querySelector('.tour-next').textContent.match(/Done|סיום/)) {
    click(document.querySelector('.tour-next'));
    titles.push(document.querySelector('.tour-title').textContent);
  }
  return titles;
}

test('the eight steps visit file, outline, search, speakers, playback, editing, flags and export, in that reading order', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);

  assert.deepEqual(titleSequence(document), [
    'This recording', 'Files and speakers', 'Search',
    'Speaker names and colours', 'Play a moment', 'Editing the transcript',
    'Show uncertain words', 'Save a copy',
  ]);

  window.close();
});

test('the degenerate document\'s five steps skip outline, speakers and playback but keep the reading order of what is left', () => {
  const { window, document } = buildWindow(getFixtureHtml('degenerate'));
  startTour(document);

  assert.deepEqual(titleSequence(document), [
    'This recording', 'Search', 'Editing the transcript',
    'Show uncertain words', 'Save a copy',
  ]);

  window.close();
});

test('the speakers step highlights the active file\'s strip, not always file 0\'s', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  // bindOutline() marks a strip .active on an outline-file link click (see
  // setActiveFile()) - this is the same mechanism a reader scrolling to a
  // later file before opening help would trigger via the IntersectionObserver,
  // which jsdom does not implement, so the click is the reachable proxy for
  // "file 1 is now the active one".
  click(document.querySelector('.outline-file[data-file="1"]'));
  assert.ok(document.querySelector('.speakers[data-file="1"]').classList.contains('active'));

  const file0Strip = document.querySelector('.speakers[data-file="0"]');
  const file1Strip = document.querySelector('.speakers[data-file="1"]');

  withRoutedRect(window, (el) => {
    if (el === file0Strip) return rect({ top: 900, left: 0, right: 200, bottom: 950, width: 200, height: 50 });
    if (el === file1Strip) return rect({ top: 200, left: 0, right: 200, bottom: 250, width: 200, height: 50 });
    return null;
  }, () => {
    startTour(document);
    // Steps: file, outline, search, speakers - three Next clicks reach it.
    click(document.querySelector('.tour-next'));
    click(document.querySelector('.tour-next'));
    click(document.querySelector('.tour-next'));
  });

  assert.equal(document.querySelector('.tour-title').textContent, 'Speaker names and colours');
  const ring = document.querySelector('.tour-ring');
  // pad = 6 (see updateTourSpotlight()) - file1Strip's stubbed top (200)
  // minus the pad is what the ring must be drawn at if file 1's strip, not
  // file 0's, was the one actually highlighted.
  assert.equal(ring.style.top, `${200 - 6}px`);

  window.close();
});

test('the spotlight ring and card are positioned from the current step\'s own target rect', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const fileBar = document.querySelector('.file-bar');

  withRoutedRect(window, (el) => {
    if (el === fileBar) return rect({ top: 40, left: 10, right: 500, bottom: 90, width: 490, height: 50 });
    return null;
  }, () => {
    startTour(document);
  });

  const ring = document.querySelector('.tour-ring');
  const pad = 6;
  assert.equal(ring.style.top, `${40 - pad}px`);
  assert.equal(ring.style.left, `${10 - pad}px`);
  assert.equal(ring.style.width, `${490 + pad * 2}px`);
  assert.equal(ring.style.height, `${50 + pad * 2}px`);

  // The card is anchored the same way any other detached popover is (see
  // positionDetachedMenu(), reused here for the tour card) - its top tracks
  // 4px below the target's own bottom edge.
  const card = document.getElementById('tour-card');
  assert.equal(card.style.top, `${90 + 4}px`);

  window.close();
});

test('resizing or scrolling after the tour starts recomputes the spotlight against the target\'s current rect', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const fileBar = document.querySelector('.file-bar');
  let currentRect = rect({ top: 40, left: 10, right: 500, bottom: 90, width: 490, height: 50 });

  const proto = window.Element.prototype;
  const original = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () {
    return this === fileBar ? currentRect : original.call(this);
  };

  startTour(document);
  assert.equal(document.querySelector('.tour-ring').style.top, `${40 - 6}px`);

  // The page (or the toolbar becoming sticky, or a window resize) moved the
  // target - scheduleTourUpdate() only re-measures on the next 'resize' or
  // capture-phase 'scroll' event, via a requestAnimationFrame callback, so
  // the test has to fire one of those and then actually wait a frame.
  currentRect = rect({ top: 140, left: 10, right: 500, bottom: 190, width: 490, height: 50 });
  window.dispatchEvent(new window.Event('resize'));
  await new Promise((resolve) => window.requestAnimationFrame(resolve));

  assert.equal(document.querySelector('.tour-ring').style.top, `${140 - 6}px`, 'a resize must trigger a recompute against the target\'s new rect');

  proto.getBoundingClientRect = original;
  window.close();
});

test('advancing a step scrolls the new target into view, honouring reduced motion', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const calls = [];
  window.HTMLElement.prototype.scrollIntoView = function (opts) { calls.push(opts); };

  startTour(document);
  assert.equal(calls.length, 1);
  // Plain-object equality across the jsdom vm realm boundary, not
  // assert.deepEqual: an object literal built inside the window's own
  // realm has a different Object.prototype identity than one built in this
  // test file, which deepStrictEqual (what node:assert/strict's deepEqual
  // aliases to) treats as unequal even with identical own properties.
  assert.equal(calls[0].behavior, 'smooth');
  assert.equal(calls[0].block, 'center');

  // scrollBehavior() checks prefers-reduced-motion at call time, not once at
  // load - flip it and confirm the very next step's scroll honours it.
  window.matchMedia = function (query) {
    return { media: query, matches: true, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
  };
  click(document.querySelector('.tour-next'));

  assert.equal(calls.length, 2);
  assert.equal(calls[1].behavior, 'auto');
  assert.equal(calls[1].block, 'center');

  window.close();
});

test('Tab traps focus inside the tour card, wrapping from the last button back to the first and Shift+Tab back again', () => {
  // Exercises the same trapTabKey()/focusableIn() pair bindHelp() uses for
  // the help panel (see help.test.mjs's own comment for why the help
  // panel's own focusable set - ending on a decorative SVG icon jsdom
  // cannot actually focus - is not the cleaner place to prove this). The
  // tour card's own actions row is nothing but plain <button> elements, so
  // both ends of the wrap are things jsdom can really move focus onto.
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const card = startTour(document);

  // Step 0: Back is hidden, so the focusable set is exactly [skip, next].
  const skip = document.querySelector('.tour-skip');
  const next = document.querySelector('.tour-next');
  assert.equal(document.querySelector('.tour-back').hidden, true);

  next.focus();
  assert.equal(document.activeElement, next);
  const forward = new window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
  card.dispatchEvent(forward);
  assert.equal(forward.defaultPrevented, true);
  assert.equal(document.activeElement, skip, 'Tab on the last button must wrap to the first');

  const backward = new window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true });
  card.dispatchEvent(backward);
  assert.equal(backward.defaultPrevented, true);
  assert.equal(document.activeElement, next, 'Shift+Tab on the first button must wrap to the last');

  window.close();
});

test('the step counter is wrapped in a bidi isolate and marked dir="ltr"', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  startTour(document);

  const count = document.querySelector('.tour-count');
  assert.equal(count.getAttribute('dir'), 'ltr');
  // PLAIN_LRI/PLAIN_PDI (U+2066/U+2069) - the same isolate the plain-text
  // panel's bracketed timestamps use (see bracketedRange() and the module
  // docstring's LRI/PDI discussion). Without it, "1 / 8" inside an RTL card
  // once rendered as "8 / 1" - the bug this guards.
  assert.equal(count.textContent, '⁦1 / 8⁩');

  window.close();
});
