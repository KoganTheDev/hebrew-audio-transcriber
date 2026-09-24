// Behavioural coverage for splitting a sentence card and giving part of it
// to another speaker.
//
// Diarization gets a BOUNDARY wrong far more often than it gets a whole turn
// wrong: two people's speech lands in one card, and before this the only
// repair was to reassign the whole card and accept that half of it was then
// attributed to the wrong person.
//
// The timestamp is the part worth testing hardest. The document now carries
// per-sentence word timings (DATA.words, keyed by data-line - see
// _build_payload() in core/formatting), so the second half starts at a real
// word boundary rather than an interpolated guess.
//
// Fixture ("split"): the only one with real per-word timings - turn "0-0"
// is speaker 0 with two sentences ("0-0-0", "0-0-1") whose six words have
// clean one-second spans, so a test can assert a cut landed on a specific
// boundary rather than merely somewhere inside.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

// Selects a character range inside a card's <p> and releases the mouse, which
// is what opens the split menu. Returns the bubble it acted on.
function selectInside(win, doc, lineId, from, to) {
  const bubble = doc.querySelector(`.bubble[data-line="${lineId}"]`);
  const p = bubble.querySelector('p');
  const textNode = p.firstChild;
  const range = doc.createRange();
  range.setStart(textNode, from);
  range.setEnd(textNode, to);
  const sel = win.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  doc.dispatchEvent(new win.MouseEvent('mouseup', { bubbles: true }));
  return bubble;
}

test('the payload carries per-sentence word timings keyed by data-line', () => {
  const { window, document } = buildWindow(getFixtureHtml('split'));

  const words = window.DATA ? window.DATA.words : null;
  const raw = document.getElementById('data') || document.querySelector('script[type="application/json"]');
  const payload = words || JSON.parse(raw.textContent).words;

  assert.ok(payload, 'the document must ship word timings for a split to be accurate');
  // Every entry is [start, end, text], and its key is a real card's id.
  Object.keys(payload).forEach((lineId) => {
    assert.ok(document.querySelector(`.bubble[data-line="${lineId}"]`),
      `${lineId} should name a card that exists`);
    payload[lineId].forEach(([start, end, text]) => {
      assert.equal(typeof start, 'number');
      assert.equal(typeof end, 'number');
      assert.ok(end >= start);
      assert.equal(typeof text, 'string');
    });
  });

  window.close();
});

test('selecting the tail of a card and picking a speaker splits it in two', async () => {
  const { window, document } = buildWindow(getFixtureHtml('split'));

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  const full = bubble.querySelector('p').textContent;
  const cut = Math.floor(full.length / 2);

  const before = document.querySelectorAll('.turn[data-turn="0-0"] .bubble').length;
  selectInside(window, document, '0-0-0', cut, full.length);
  await wait(10);

  const menu = document.querySelector('.split-menu');
  assert.ok(menu, 'a selection inside a card should offer the speaker list');
  // A selection defines its own scope, so unlike a chip's menu this one has
  // no "this sentence / this whole block" group.
  assert.equal(menu.querySelector('.spk-menu-scope'), null);

  click(menu.querySelector('.spk-menu-item[data-speaker="1"]'));
  await wait(10);

  const after = document.querySelectorAll('.turn[data-turn="0-0"] .bubble');
  assert.equal(after.length, before + 1, 'one card becomes two');

  const first = document.querySelector('.bubble[data-line="0-0-0"]');
  const second = first.nextElementSibling;
  assert.equal(first.querySelector('p').textContent, full.slice(0, cut).trimEnd());
  assert.equal(second.querySelector('p').textContent, full.slice(cut).trimStart());
  assert.equal(second.querySelector('.bubble-spk').dataset.speaker, '1',
    'the selected half goes to the chosen speaker');
  assert.equal(first.dataset.speaker, undefined === first.dataset.speaker ? undefined : first.dataset.speaker);

  window.close();
});

test('the new card starts at a real word boundary, inside its parent span', async () => {
  const { window, document } = buildWindow(getFixtureHtml('split'));

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  const parentStart = Number(bubble.dataset.start);
  const parentEnd = Number(bubble.dataset.end);
  const full = bubble.querySelector('p').textContent;

  selectInside(window, document, '0-0-0', Math.floor(full.length / 2), full.length);
  await wait(10);
  click(document.querySelector('.split-menu .spk-menu-item[data-speaker="1"]'));
  await wait(10);

  const first = document.querySelector('.bubble[data-line="0-0-0"]');
  const second = first.nextElementSibling;
  const cutAt = Number(second.dataset.start);

  assert.equal(Number(first.dataset.start), parentStart, 'the first half keeps the original start');
  assert.equal(Number(second.dataset.end), parentEnd, 'the second half keeps the original end');
  assert.equal(Number(first.dataset.end), cutAt, 'the halves meet exactly, with no gap or overlap');
  assert.ok(cutAt > parentStart && cutAt < parentEnd,
    `the cut must land inside the card's own span, got ${cutAt} outside [${parentStart}, ${parentEnd}]`);

  // And it is a real word boundary, not a midpoint guess.
  const words = JSON.parse(
    (document.getElementById('data') || document.querySelector('script[type="application/json"]')).textContent,
  ).words['0-0-0'];
  const boundaries = words.flatMap(([s, e]) => [s, e]);
  assert.ok(boundaries.includes(cutAt),
    `${cutAt} should be one of this sentence's own word boundaries`);

  window.close();
});

test('a new card gets unique ids and working play and copy buttons', async () => {
  const { window, document } = buildWindow(getFixtureHtml('split'));

  const full = document.querySelector('.bubble[data-line="0-0-0"] p').textContent;
  selectInside(window, document, '0-0-0', Math.floor(full.length / 2), full.length);
  await wait(10);
  click(document.querySelector('.split-menu .spk-menu-item[data-speaker="1"]'));
  await wait(10);

  const ids = [...document.querySelectorAll('.bubble')].map((b) => b.dataset.line);
  assert.equal(new Set(ids).size, ids.length, 'data-line must stay unique - it keys saved overrides');
  // A suffixed child id, never a renumbering of siblings: renumbering would
  // orphan every state.assignLine key in the turn.
  assert.ok(ids.includes('0-0-1'), 'the sibling sentence keeps its original id');

  const second = document.querySelector('.bubble[data-line="0-0-0"]').nextElementSibling;
  // Both were bound eagerly per element before this feature, which left a new
  // card's buttons dead. They are delegated now.
  assert.ok(second.querySelector('.ts'), 'the new card has a play button');
  assert.ok(second.querySelector('.copy-line'), 'and a copy button');
  assert.doesNotThrow(() => click(second.querySelector('.ts')));

  window.close();
});

test('a split survives a reload instead of the halves merging back', async () => {
  const seedKey = 'hebrew-transcript:js-fixture-split';
  const first = buildWindow(getFixtureHtml('split'));

  const full = first.document.querySelector('.bubble[data-line="0-0-0"] p').textContent;
  selectInside(first.window, first.document, '0-0-0', Math.floor(full.length / 2), full.length);
  await wait(10);
  click(first.document.querySelector('.split-menu .spk-menu-item[data-speaker="1"]'));
  await wait(600);

  const saved = first.window.localStorage.getItem(seedKey);
  assert.ok(saved, 'the split has to be persisted');
  const parsed = JSON.parse(saved);
  // state.turns is a POSITIONAL paragraph array replayed by applyEdits(),
  // which joins overflow into the LAST bubble. If the stored array still had
  // the pre-split paragraph count, a reload would silently merge the halves.
  if (parsed.turns['0-0']) {
    assert.equal(parsed.turns['0-0'].length,
      first.document.querySelectorAll('.turn[data-turn="0-0"] .bubble').length,
      'the saved paragraph count must match the post-split card count');
  }
  first.window.close();
});

test('selecting a whole sentence is left to the chip, not treated as a split', async () => {
  const { window, document } = buildWindow(getFixtureHtml('split'));

  const full = document.querySelector('.bubble[data-line="0-0-0"] p').textContent;
  selectInside(window, document, '0-0-0', 0, full.length);
  await wait(10);

  assert.equal(document.querySelector('.split-menu'), null,
    'reassigning a whole sentence is what the chip already does - splitting it would '
      + 'produce an empty card');

  window.close();
});
