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
    ts: bubble.querySelector('.ts').textContent,
  };

  const p = bubble.querySelector('p');
  p.textContent = 'שלום מתוקן';
  turn.querySelector('.body').dispatchEvent(new window.Event('input', { bubbles: true }));

  const after = document.querySelector('.bubble[data-line="0-0-0"]');
  assert.equal(after.dataset.line, before.dataLine);
  assert.equal(after.dataset.start, before.dataStart);
  assert.equal(after.dataset.end, before.dataEnd);
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

test('a line break typed inside one plain-line stays inside that one sentence, not a new bubble', () => {
  // The plain panel is one .plain-line per BUBBLE now (see
  // core/formatting/document.py's _render_plain_html() and rebuildPlain()
  // in js/32-plain-text.js) - a 1:1 mapping, not the old one-.plain-row-
  // per-TURN shape where several sentences shared one editable body and an
  // extra typed line had nowhere of its own to go. writeParagraphs()'s own
  // "fold overflow into the last bubble" behaviour (still exercised below,
  // via a genuine multi-paragraph card edit) is therefore no longer
  // reachable through the plain panel at all: an embedded line break typed
  // into a single .plain-line's .plain-body just becomes part of that one
  // sentence's own text.
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');
  assert.equal(body.querySelectorAll('.bubble').length, 2, 'starts with two bubbles');

  const line = document.querySelector('.plain-line[data-line="0-0-1"]');
  const bodyEl = line.querySelector('.plain-body');
  bodyEl.textContent += '\nעוד שורה בלי תזמון';
  bodyEl.dispatchEvent(new window.Event('input', { bubbles: true }));

  const bubbles = body.querySelectorAll('.bubble');
  assert.equal(bubbles.length, 2, 'no new bubble may be invented for an embedded line break');
  assert.equal(bubbles[0].querySelector('p').textContent, 'שלום אחד שתיים שלוש.');
  assert.equal(
    bubbles[1].querySelector('p').textContent,
    'עוד משפט קצר\nעוד שורה בלי תזמון',
    'the line break must stay inside this one sentence\'s own text'
  );
  // This bubble's own timing must be untouched - editing its text through
  // the panel does not touch data-start/data-end.
  assert.equal(bubbles[1].dataset.start, '1.00');
  assert.equal(bubbles[1].dataset.end, '3.00');

  window.close();
});

test('writeParagraphs() still folds overflow text into the last bubble when a saved edit replays more paragraphs than bubbles', () => {
  // The fold behaviour itself (js/16-edits.js's writeParagraphs()) is still
  // real - applyEdits() (99-init.js, run on every page load) can replay a
  // saved paragraph array longer than the card's current bubble count (e.g.
  // after a previous session trimmed the card down) - it is simply no
  // longer something the PLAIN PANEL's own input handler can trigger, per
  // the test above. Driven here by seeding localStorage with exactly that
  // saved array and letting the page's own top-to-bottom load() +
  // applyEdits() sequence replay it, the same "seed, then build the window"
  // pattern line-speaker.test.mjs uses for a reload.
  const html = getFixtureHtml('full');
  const key = 'hebrew-transcript:js-fixture-full';
  const seed = {
    turns: { '0-0': ['שלום אחד שתיים שלוש.', 'עוד משפט קצר', 'עוד שורה בלי תזמון'] },
    names: {}, flags: false, theme: null, opts: {}, speakers: {}, assign: {}, assignLine: {},
  };
  const { window, document } = buildWindow(html, { [key]: JSON.stringify(seed) });
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  const bubbles = body.querySelectorAll('.bubble');
  assert.equal(bubbles.length, 2, 'no third bubble may be invented for text with no timing');
  assert.equal(bubbles[0].querySelector('p').textContent, 'שלום אחד שתיים שלוש.');
  assert.equal(
    bubbles[1].querySelector('p').textContent,
    'עוד משפט קצר עוד שורה בלי תזמון',
    'the overflow paragraph must be folded into the last bubble\'s text, space-joined'
  );
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
  const firstLine = document.querySelector('.plain-line[data-line="0-0-0"] .plain-body');
  const secondLine = document.querySelector('.plain-line[data-line="0-0-1"] .plain-body');

  // Sanity check on the fixture itself: each line really does carry the
  // "{LRI}{n}{PDI}. {LRI}[range]{PDI} " lead-in before anything is typed -
  // the fixture renders with timestamps on, so each line's own range is
  // present too, not just its number.
  assert.equal(firstLine.textContent, `${LRI}1${PDI}. ${LRI}[0:00 - 0:01]${PDI} שלום אחד שתיים שלוש.`);
  assert.equal(secondLine.textContent, `${LRI}2${PDI}. ${LRI}[0:01 - 0:03]${PDI} עוד משפט קצר`);

  // Simulate typing a correction into the first line without disturbing its
  // leading "{LRI}1{PDI}. {LRI}[0:00 - 0:01]{PDI} " - textContent is edited directly
  // (jsdom does not implement contenteditable typing) and an 'input' event
  // is fired the way a real keystroke would.
  const bodyEl = firstLine;
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
  // sentences to one, so every sentence number downstream of it (turn
  // 0-1's own line, numbered 3 by the server render) has to shift down by
  // one, and the deleted sentence's own .plain-line must disappear too.
  turn.querySelector('.bubble[data-line="0-0-1"]').remove();
  body.dispatchEvent(new window.Event('input', { bubbles: true }));

  assert.equal(document.querySelector('.plain-line[data-line="0-0-1"]'), null,
    'the removed sentence\'s own line must be gone, not just skipped');

  const line000 = document.querySelector('.plain-line[data-line="0-0-0"] .plain-body');
  assert.equal(line000.textContent, `${LRI}1${PDI}. ${LRI}[0:00 - 0:01]${PDI} שלום אחד שתיים שלוש.`);

  const line010 = document.querySelector('.plain-line[data-line="0-1-0"] .plain-body');
  assert.equal(line010.textContent, `${LRI}2${PDI}. ${LRI}[0:05 - 0:08]${PDI} שלום ארבע חמש שש`);

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

// There is no more cluster-header .ts to play a whole turn from - the
// header that carried one is gone (see the review plan's "flat sentence
// cards" section); every play control is a bubble's own now, covered by
// "clicking a bubble's .ts sets playback bounds from that bubble" above.

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
// feature); the per-card copy-line button must never emit them.
//
// copy-line's own bracketed-range-and-speaker prefix (bubblePlainText() in
// js/32-plain-text.js) is the direct replacement for the old cluster-level
// copy-turn action, which had no home left once the header went away - so
// this test's job is narrower than "no digits at all": the plain-panel's
// own per-sentence "{LRI}{n}{PDI}. {LRI}[range]{PDI} " lead-in (the thing
// readParagraphs() also has to steer clear of - see js/16-edits.js) must
// never leak into the copy, even though the sentence's own timestamp
// legitimately carries digits of its own.
// -----------------------------------------------------------------------

test('copy-line carries the sentence\'s own timestamp/speaker prefix but never its plain-panel line-number', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  const btn = bubble.querySelector('.copy-line');

  const writes = [];
  window.navigator.clipboard = { writeText: (text) => { writes.push(text); return Promise.resolve(); } };

  click(btn);
  await wait(0);

  assert.equal(writes.length, 1);
  // Leads with U+200F RLM: this text opens with a bracketed timestamp, an
  // LTR run, and apps that guess paragraph direction from the first strong
  // character would left-align the Hebrew behind it. See anchorRtl() in
  // js/32-plain-text.js, and tests/js/copy-rtl.test.mjs which covers the
  // anchoring itself.
  assert.equal(writes[0], `‏${LRI}[0:00 - 0:01]${PDI} Speaker 1: שלום אחד שתיים שלוש.`);
  assert.ok(!writes[0].includes(`${LRI}1${PDI}. `), 'must not carry the plain panel\'s own "1." line-number lead-in');

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
  assert.ok(writes[0].includes(`${LRI}1${PDI}. ${LRI}[0:00 - 0:01]${PDI} `), 'expected the first sentence\'s number and range to survive into the copy');
  assert.ok(writes[0].includes(`${LRI}2${PDI}. ${LRI}[0:01 - 0:03]${PDI} `), 'expected the second sentence\'s number and range too');

  window.close();
});
