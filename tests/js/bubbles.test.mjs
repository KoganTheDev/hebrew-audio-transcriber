// Behavioural coverage for the sentence-bubble markup itself: the level
// under a card's .body that split from one bare <p> per paragraph into one
// <div class="bubble"> per sentence (see _render_bubble_html() in
// core/formatting/document.py). readParagraphs()/writeParagraphs()
// (js/16-edits.js), the plain-panel writeback (js/32-plain-text.js) and
// per-bubble playback (js/64-audio.js) all had to change for this shape,
// and this file is what proves each one actually did rather than merely
// continuing to pass by accident - see editing.test.mjs and
// plain-text.test.mjs, which exercise the surrounding turn/panel mechanics
// but never touch a bubble's own <p> or a bubble's own .ts.
//
// tests/js/render_fixture.py's "full" fixture gives turn 0-0 two sentences
// (a period after "שלוש") specifically so this file has a real multi-bubble
// turn to test a paragraph-count change against, not just a single-bubble
// one where "the count changed" could only ever mean "went to zero".

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

const LRI = '⁦';
const PDI = '⁩';

function fire(el, type) {
  el.dispatchEvent(new el.ownerDocument.defaultView.Event(type, { bubbles: true }));
}

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// -----------------------------------------------------------------------
// readParagraphs()/writeParagraphs() - the edit round-trip through a card.
// -----------------------------------------------------------------------

test('typing into a bubble\'s <p> leaves the wrapper, its attributes and its siblings untouched', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const bubble = turn.querySelector('.bubble[data-line="0-0-0"]');

  const before = {
    dataLine: bubble.dataset.line,
    dataStart: bubble.dataset.start,
    dataEnd: bubble.dataset.end,
    lineNo: bubble.querySelector('.line-no').textContent,
    ts: bubble.querySelector('.ts').textContent,
  };

  const p = bubble.querySelector('p');
  p.textContent = 'שלום מתוקן';
  turn.querySelector('.body').dispatchEvent(new window.Event('input', { bubbles: true }));

  const after = document.querySelector('.bubble[data-line="0-0-0"]');
  assert.equal(after.dataset.line, before.dataLine);
  assert.equal(after.dataset.start, before.dataStart);
  assert.equal(after.dataset.end, before.dataEnd);
  assert.equal(after.querySelector('.line-no').textContent, before.lineNo);
  assert.equal(after.querySelector('.ts').textContent, before.ts);
  assert.equal(after.querySelector('p').textContent, 'שלום מתוקן');
  assert.ok(after.classList.contains('bubble'), 'the wrapper must still be a .bubble');

  // The turn's second bubble (0-0-1) must be completely unaffected by an
  // edit inside the first.
  const second = turn.querySelector('.bubble[data-line="0-0-1"]');
  assert.ok(second, 'the second bubble must still exist');
  assert.equal(second.querySelector('p').textContent, 'עוד משפט קצר');

  window.close();
});

test('an edited card is saved as a paragraph array with no line-number or timestamp text baked in', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const bubble = turn.querySelector('.bubble[data-line="0-0-0"]');

  bubble.querySelector('p').textContent = 'שלום מתוקן';
  turn.querySelector('.body').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(500);

  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.deepEqual(saved.turns['0-0'], ['שלום מתוקן', 'עוד משפט קצר']);

  window.close();
});

test('deleting a whole sentence drops the paragraph count and removes the trailing bubble', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  assert.equal(body.querySelectorAll('.bubble').length, 2, 'fixture turn 0-0 starts with two bubbles');

  // Simulate a reader deleting the second sentence entirely, the way a
  // contenteditable edit that removes a trailing block would leave things:
  // one <p> gone, one bubble's worth of wrapper gone with it.
  turn.querySelector('.bubble[data-line="0-0-1"]').remove();
  body.dispatchEvent(new window.Event('input', { bubbles: true }));

  assert.equal(body.querySelectorAll('.bubble').length, 1);
  assert.equal(body.querySelector('p').textContent, 'שלום אחד שתיים שלוש.');

  window.close();
});

test('an extra line typed into the plain panel folds into the card\'s last bubble, not a new one', () => {
  // Drives writeParagraphs() through its real caller - the plain panel's
  // own input handler (js/32-plain-text.js) - rather than calling it by
  // hand, so this proves the fold behaviour end to end: three lines synced
  // from a row whose card only has two bubbles' worth of real timing.
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');
  assert.equal(body.querySelectorAll('.bubble').length, 2, 'starts with two bubbles');

  const row = document.querySelector('.plain-row[data-turn="0-0"]');
  const bodyEl = row.querySelector('.plain-body');
  // A third line has nowhere with real timing to go - a reader pressing
  // Enter mid-row is exactly how this would arise from actual typing.
  bodyEl.textContent += '\nעוד שורה בלי תזמון';
  bodyEl.dispatchEvent(new window.Event('input', { bubbles: true }));

  const bubbles = body.querySelectorAll('.bubble');
  assert.equal(bubbles.length, 2, 'no third bubble may be invented for text with no timing');
  assert.equal(bubbles[0].querySelector('p').textContent, 'שלום אחד שתיים שלוש.');
  assert.equal(
    bubbles[1].querySelector('p').textContent,
    'עוד משפט קצר עוד שורה בלי תזמון',
    'the overflow line must be folded into the last bubble\'s text, space-joined'
  );
  // The folded-into bubble's own timing must be untouched - it still owns
  // whatever span the renderer gave it, not something invented for the
  // extra text.
  assert.equal(bubbles[1].dataset.start, '1.00');
  assert.equal(bubbles[1].dataset.end, '3.00');

  window.close();
});

// -----------------------------------------------------------------------
// The plain-panel writeback bug - stripping the leading line number before
// it reaches writeParagraphs().
// -----------------------------------------------------------------------

test('editing the plain panel never bakes the line-number lead-in into the card text', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  const row = document.querySelector('.plain-row[data-turn="0-0"]');
  const bodyEl = row.querySelector('.plain-body');

  // Sanity check on the fixture itself: the row really does carry the
  // "{LRI}{n}{PDI} " lead-in on both of its lines before anything is typed.
  assert.ok(bodyEl.textContent.startsWith(`${LRI}1${PDI} `), 'expected the first line\'s number lead-in');
  assert.ok(bodyEl.textContent.includes(`\n${LRI}2${PDI} `), 'expected the second line\'s number lead-in');

  // Simulate typing a correction into the first line without disturbing its
  // leading "{LRI}1{PDI} " - textContent is edited directly (jsdom does not
  // implement contenteditable typing) and an 'input' event is fired the way
  // a real keystroke would.
  bodyEl.textContent = bodyEl.textContent.replace('שלום אחד', 'שלום מתוקן');
  bodyEl.dispatchEvent(new window.Event('input', { bubbles: true }));

  const card = document.querySelector('.turn[data-turn="0-0"] .bubble[data-line="0-0-0"] p');
  assert.equal(card.textContent, 'שלום מתוקן שתיים שלוש.');
  assert.ok(!/[0-9]/.test(card.textContent), 'the card text must carry no digits from the stripped line number');
  assert.ok(!card.textContent.includes(LRI) && !card.textContent.includes(PDI),
    'the card text must carry no bidi isolate characters either');

  await wait(500);
  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.deepEqual(saved.turns['0-0'], ['שלום מתוקן שתיים שלוש.', 'עוד משפט קצר']);

  window.close();
});

// -----------------------------------------------------------------------
// rebuildPlain() regenerating numbers when a card edit changes the panel.
// -----------------------------------------------------------------------

test('editing a card renumbers the plain panel to match its new paragraph count', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  // Delete the second sentence in the card - turn 0-0 drops from two
  // paragraphs to one, so every sentence number downstream of it (turn
  // 0-1's row, numbered 3 by the server render) has to shift down by one.
  turn.querySelector('.bubble[data-line="0-0-1"]').remove();
  body.dispatchEvent(new window.Event('input', { bubbles: true }));

  const row00 = document.querySelector('.plain-row[data-turn="0-0"]');
  assert.equal(row00.querySelector('.plain-body').textContent, `${LRI}1${PDI} שלום אחד שתיים שלוש.`);

  const row01 = document.querySelector('.plain-row[data-turn="0-1"]');
  assert.equal(row01.querySelector('.plain-body').textContent, `${LRI}2${PDI} שלום ארבע חמש שש`);

  window.close();
});

// -----------------------------------------------------------------------
// Per-bubble playback.
// -----------------------------------------------------------------------

test('clicking a bubble\'s .ts sets playback bounds from that bubble, not the turn', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const audio = document.getElementById('audio');
  // jsdom does not implement HTMLMediaElement.play() - it returns undefined
  // rather than a Promise, so bindAudio()'s own `.catch()` on the result
  // would throw. Stubbed here the same way chrome.test.mjs stubs audio.paused
  // for the play/pause glyph test, rather than leaving the real click handler
  // to hit that gap.
  audio.play = () => Promise.resolve();

  const first = document.querySelector('.bubble[data-line="0-0-0"] .ts');
  const second = document.querySelector('.bubble[data-line="0-0-1"] .ts');
  assert.equal(first.closest('.bubble').dataset.start, '0.00');
  assert.equal(first.closest('.bubble').dataset.end, '1.00');
  assert.equal(second.closest('.bubble').dataset.start, '1.00');
  assert.equal(second.closest('.bubble').dataset.end, '3.00');

  click(first);
  assert.equal(audio.currentTime, 0, 'the first bubble starts at 0');

  // Sweep past the first bubble's own end (1.00s) but well short of the
  // turn's end (3.00s) - if the bound came from the turn instead of the
  // bubble, playback would sail straight through this without stopping.
  Object.defineProperty(audio, 'currentTime', { value: 1.2, writable: true, configurable: true });
  fire(audio, 'timeupdate');
  assert.equal(audio.currentTime, 1, 'must clamp to the bubble\'s own end, not the turn\'s');

  click(second);
  assert.equal(audio.currentTime, 1, 'the second bubble starts where the first one ended');

  Object.defineProperty(audio, 'currentTime', { value: 3.5, writable: true, configurable: true });
  fire(audio, 'timeupdate');
  assert.equal(audio.currentTime, 3, 'must clamp to the second bubble\'s own end');

  window.close();
});

test('the turn header\'s .ts still plays the whole turn, unaffected by per-bubble playback', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const audio = document.getElementById('audio');
  audio.play = () => Promise.resolve();

  const header = document.querySelector('.turn[data-turn="0-0"] h2 > .ts');
  assert.equal(header.dataset.start, '0.00');
  assert.equal(header.dataset.end, '3.00');

  click(header);
  assert.equal(audio.currentTime, 0);

  // Past the first bubble's end (1.00s), which must NOT stop turn-header
  // playback the way it stops a bubble click.
  Object.defineProperty(audio, 'currentTime', { value: 1.5, writable: true, configurable: true });
  fire(audio, 'timeupdate');
  assert.equal(audio.currentTime, 1.5, 'the turn-level bound only stops playback at 3.00, not 1.00');

  Object.defineProperty(audio, 'currentTime', { value: 3.2, writable: true, configurable: true });
  fire(audio, 'timeupdate');
  assert.equal(audio.currentTime, 3, 'must clamp to the turn\'s own end');

  window.close();
});

// -----------------------------------------------------------------------
// Search must still find and step into text nested one level deeper (inside
// a .bubble now, not a bare <p> directly under .body).
// -----------------------------------------------------------------------

test('search still finds and marks text inside a bubble', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const box = document.getElementById('search');

  box.value = 'שלום';
  box.dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(300);

  const hit = document.querySelector('mark.hit');
  assert.ok(hit, 'expected at least one match');
  assert.ok(hit.closest('.bubble'), 'the match must be inside a .bubble, not floating loose in .body');
  assert.ok(hit.closest('p'), 'the match must still be inside the bubble\'s own <p>');

  window.close();
});

// -----------------------------------------------------------------------
// Export/copy: the plain panel keeps the numbers (that is the point of the
// feature); the per-card copy-turn button must never emit them.
//
// copy-turn's own bracketed-range-and-speaker prefix (turnPlainText(turn,
// true, true) in js/32-plain-text.js) predates the sentence-bubbles work
// entirely and is deliberate - see bindPlain()'s own copy-turn wiring - so
// this test's job is narrower than "no digits at all": the bubble's own
// per-sentence "{LRI}{n}{PDI} " line-number lead-in (new in this branch,
// and the thing readParagraphs() also has to steer clear of - see
// js/16-edits.js) must never leak into the copy, even though the turn's
// timestamp legitimately carries digits of its own.
// -----------------------------------------------------------------------

test('copy-turn carries the turn\'s own timestamp/speaker prefix but never a bubble\'s line-number', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const btn = turn.querySelector('.copy-turn');

  const writes = [];
  window.navigator.clipboard = { writeText: (text) => { writes.push(text); return Promise.resolve(); } };

  click(btn);
  await wait(0);

  assert.equal(writes.length, 1);
  assert.equal(writes[0], `${LRI}[0:00 - 0:03]${PDI} Speaker 1: שלום אחד שתיים שלוש.\nעוד משפט קצר`);
  assert.ok(!writes[0].includes(`${LRI}1${PDI} `), 'must not carry the first bubble\'s own "1" line-number');
  assert.ok(!writes[0].includes(`${LRI}2${PDI} `), 'must not carry the second bubble\'s own "2" line-number');

  window.close();
});

test('the plain panel\'s "copy all" keeps the sentence numbers - that is the point of the panel', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = document.querySelector('.source[data-file="0"] .plain');
  const btn = panel.querySelector('.copy-all');

  const writes = [];
  window.navigator.clipboard = { writeText: (text) => { writes.push(text); return Promise.resolve(); } };

  click(btn);
  await wait(0);

  assert.equal(writes.length, 1);
  assert.ok(writes[0].includes(`${LRI}1${PDI} `), 'expected the first sentence\'s number to survive into the copy');
  assert.ok(writes[0].includes(`${LRI}2${PDI} `), 'expected the second sentence\'s number too');

  window.close();
});
