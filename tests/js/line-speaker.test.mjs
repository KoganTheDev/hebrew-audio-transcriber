// Behavioural coverage for per-bubble speaker overrides - the sentence-level
// counterpart to turn reassignment (see speakers.test.mjs) added for the "no
// feature loss" checklist's "Reassign speaker" row: the .spk chip only ever
// moves a whole cluster (up to 30s), so a single mislabelled sentence could
// not be fixed by hand at all until this control existed.
//
// state.assignLine[lineId] (js/00-preamble.js), reassignLine()/
// paintBubbleOverride()/applyLineAssignments() (js/24-speakers-menus.js) and
// rebuildPlain()'s per-sentence heading grouping (js/32-plain-text.js) are
// exercised here against the real rendered page, the same way every other
// *.test.mjs in this directory drives real markup rather than a
// hand-written stand-in - see harness.mjs's own module docstring.
//
// Fixture recap (render_fixture.py's "full" build): turn "0-0" is speaker 0
// ("Speaker 1") with two sentences - bubbles "0-0-0" and "0-0-1"; turn "0-1"
// is speaker 1 ("Speaker 2") with one sentence - bubble "0-1-0". The
// mid-turn split/resume/merge tests below use the "triple" fixture instead
// - turn "0-0" is speaker 0 ("Speaker 1") with THREE sentences ("0-0-0",
// "0-0-1", "0-0-2"), and turn "0-1" is speaker 1 ("Speaker 2") with one
// sentence ("0-1-0") - the extra middle sentence is what lets a test
// override one sentence and still see a real, unoverridden sentence of the
// original speaker follow it.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('clicking a bubble\'s speaker control opens the same reassignment menu a cluster\'s .spk opens', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  click(bubble.querySelector('.bubble-spk'));

  const menu = document.querySelector('.spk-menu');
  assert.ok(menu, 'expected a reassignment menu to open');
  assert.equal(menu.querySelectorAll('.spk-menu-item').length, 2, 'file 0 has two speakers');
  // The bubble's own cluster is speaker 0 - the menu should open with THAT
  // radio checked, since no override exists yet on this bubble.
  const checked = menu.querySelector('.spk-menu-item[aria-checked="true"]');
  assert.equal(checked.dataset.speaker, '0');

  window.close();
});

test('choosing a different speaker on one bubble overrides only that bubble, leaving its sibling untouched', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const first = turn.querySelector('.bubble[data-line="0-0-0"]');
  const second = turn.querySelector('.bubble[data-line="0-0-1"]');

  click(first.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  assert.equal(first.dataset.override, 'true');
  assert.equal(first.querySelector('.bubble-spk').dataset.speaker, '1');
  assert.equal(first.querySelector('.bubble-spk-label').textContent, 'Speaker 2');
  // The turn's own dataset must be completely unaffected: this is a
  // per-sentence override, not a reassignment of the block.
  assert.equal(turn.dataset.speaker, '0');

  // The untouched sibling bubble keeps showing the BLOCK's own identity -
  // every bubble's chip is a resting identity now, never blank (see
  // _render_bubble_html()'s docstring), so "untouched" means "still reads
  // as speaker 0", not "carries no data-speaker at all".
  assert.equal(second.hasAttribute('data-override'), false);
  assert.equal(second.querySelector('.bubble-spk').dataset.speaker, '0');
  assert.equal(second.querySelector('.bubble-spk-label').textContent, 'Speaker 1');

  // The menu must close as part of picking an item, same as a cluster
  // reassignment does.
  assert.equal(document.querySelector('.spk-menu'), null);

  window.close();
});

test('picking the cluster\'s own speaker on an overridden bubble clears the override instead of storing a redundant entry', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');

  // Set an override to speaker 1 first.
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));
  assert.equal(bubble.dataset.override, 'true');

  // Now pick speaker 0 again - the bubble's own cluster - from the same
  // control.
  click(bubble.querySelector('.bubble-spk'));
  const clusterItem = document.querySelector('.spk-menu-item[data-speaker="0"]');
  assert.ok(clusterItem);
  click(clusterItem);

  assert.equal(bubble.hasAttribute('data-override'), false, 'the override must be cleared, not merely re-pointed at the cluster');
  // Clearing restores the BLOCK's own identity onto the chip - it does not
  // blank it, since every bubble's chip is a resting identity now, never an
  // empty state (see paintBubbleOverride()'s own docstring).
  assert.equal(bubble.querySelector('.bubble-spk').dataset.speaker, '0');
  assert.equal(bubble.querySelector('.bubble-spk-label').textContent, 'Speaker 1');

  await wait(500);
  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.equal(
    Object.prototype.hasOwnProperty.call(saved.assignLine, '0-0-0'), false,
    'clearing an override must delete the key, not store the cluster\'s own id under it'
  );

  window.close();
});

test('a line override autosaves under state.assignLine, keyed by the bubble\'s data-line id', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;

  const bubble = document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  await wait(500);
  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.equal(saved.assignLine['0-0-1'], 1);
  // No other bucket should have been touched by a line-only override.
  assert.deepEqual(saved.assign, {});

  window.close();
});

test('hasLocalChanges() reports true (status "local") on reload with only a line override saved', () => {
  const html = getFixtureHtml('full');
  const key = 'hebrew-transcript:js-fixture-full';

  // Seeded directly, not produced by clicking through a first window - see
  // buildWindow()'s own docstring on why a second jsdom instance cannot
  // simply inherit the first one's storage.
  const seed = { turns: {}, names: {}, flags: false, theme: null, opts: {}, speakers: {}, assign: {}, assignLine: { '0-0-1': 1 } };
  const { window, document } = buildWindow(html, { [key]: JSON.stringify(seed) });

  const status = document.getElementById('status');
  assert.equal(status.dataset.kind, 'local', 'a saved-but-unexported line override must not read as "saved"');

  window.close();
});

test('an override survives a reload, replayed from localStorage by applyLineAssignments()', () => {
  const html = getFixtureHtml('full');
  const key = 'hebrew-transcript:js-fixture-full';

  // First window: set the override and read back exactly what got saved,
  // synchronously (reassignLine() writes state.assignLine before its
  // debounced save() call, and localStorage itself only needs the debounce
  // to have fired once to read back from - simulated here by reading the
  // in-memory state's own JSON shape instead of waiting on the timer, since
  // this test only needs a realistic saved payload to seed the second
  // window with, not to prove the debounce itself, which speakers.test.mjs
  // already covers).
  const first = buildWindow(html);
  const bubble = first.document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(first.document.querySelector('.spk-menu-item[data-speaker="1"]'));

  return wait(500).then(() => {
    const saved = first.window.localStorage.getItem(key);
    first.window.close();

    // Second window: a fresh reload with nothing but that saved state.
    const second = buildWindow(html, { [key]: saved });
    const reloadedBubble = second.document.querySelector('.bubble[data-line="0-0-1"]');

    assert.equal(reloadedBubble.dataset.override, 'true');
    assert.equal(reloadedBubble.querySelector('.bubble-spk').dataset.speaker, '1');
    assert.equal(reloadedBubble.querySelector('.bubble-spk-label').textContent, 'Speaker 2');
    // Its cluster (the turn) must still read as speaker 0 - only the line
    // itself was overridden.
    const turn = second.document.querySelector('.turn[data-turn="0-0"]');
    assert.equal(turn.dataset.speaker, '0');

    second.window.close();
  });
});

// A .plain-heading is a standalone sibling of the .plain-line it heads (see
// rebuildPlain() in js/32-plain-text.js) rather than living inside it, so
// these tests read it off the line's own previousElementSibling.
function headingBefore(lineEl) {
  var sib = lineEl.previousElementSibling;
  return sib && sib.classList.contains('plain-heading') ? sib : null;
}

test('an override that makes a sentence agree with the sentence before it removes its own heading - the run merges', () => {
  // Turn "0-1" has exactly one sentence/bubble, so overriding it to speaker
  // 0 changes what its ONE line reports as its effective speaker outright -
  // no other sentence in the turn to disagree with it. Speaker 0
  // ("Speaker 1") is ALSO turn "0-0"'s own speaker, so this override makes
  // two consecutive lines agree that did not before - proof that heading
  // visibility is recomputed across the whole document after an override,
  // not decided once per line in isolation (see rebuildPlain()'s own
  // comment in js/32-plain-text.js).
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const line000 = document.querySelector('.plain-line[data-line="0-0-0"]');
  const line010 = document.querySelector('.plain-line[data-line="0-1-0"]');
  assert.equal(headingBefore(line000).textContent, 'Speaker 1', 'the first line of a document always starts a run');
  assert.equal(headingBefore(line010).textContent, 'Speaker 2', 'before the override, line 0-1-0 starts its own run');

  const bubble = document.querySelector('.bubble[data-line="0-1-0"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="0"]'));

  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-0"]')).textContent, 'Speaker 1', 'unaffected - still the first line');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-1-0"]')), null, 'line 0-1-0 now agrees with the line before it, so its heading is gone');

  window.close();
});

test('overriding a MIDDLE sentence splits its turn into two heading sections, and the original speaker resumes right after it', () => {
  // Uses the "triple" fixture (see render_fixture.py and this file's own
  // header comment): turn "0-0" has THREE sentences under one speaker, so
  // overriding only the middle one ("0-0-1") leaves a real, untouched
  // sentence of the ORIGINAL speaker ("0-0-2") right after it - proof that
  // a heading can land in the middle of a turn at all, which the old
  // one-.plain-row-per-turn shape could never express (see
  // _render_plain_html()'s docstring, core/formatting/document.py).
  const { window, document } = buildWindow(getFixtureHtml('triple'));

  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-0"]')).textContent, 'Speaker 1');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-1"]')), null, 'still one run before the override');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-2"]')), null, 'still one run before the override');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-1-0"]')).textContent, 'Speaker 2');

  const bubble = document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-0"]')).textContent, 'Speaker 1', 'unaffected');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-1"]')).textContent, 'Speaker 2', 'the overridden sentence opens its own section');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-2"]')).textContent, 'Speaker 1', 'the untouched third sentence resumes the original speaker');
  // Turn "0-1"'s own line is STILL Speaker 2, but the sentence right before
  // it ("0-0-2") just resumed Speaker 1 - so this is a fresh run of its own
  // again, not a merge, and it keeps its own heading (unchanged from before
  // the override, since nothing about ITS run boundary actually moved).
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-1-0"]')).textContent, 'Speaker 2', 'unaffected - its own run, same as before the override');

  // Overriding back to the cluster's own speaker merges the two sections
  // in turn "0-0" back into one.
  click(document.querySelector('.bubble[data-line="0-0-1"] .bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="0"]'));

  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-0"]')).textContent, 'Speaker 1');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-1"]')), null, 'merged back into the first section');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-2"]')), null, 'merged back into the first section');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-1-0"]')).textContent, 'Speaker 2', 'its own section is back too');

  window.close();
});

test('overriding a sentence to a speaker ADJACENT to an existing run merges into it instead of creating a duplicate heading', () => {
  // Overrides turn "0-0"'s LAST sentence ("0-0-2") to speaker 1 - the same
  // speaker turn "0-1"'s own sentence ("0-1-0") already is, and which
  // already immediately follows it in document order. The result must be
  // one "Speaker 2" section spanning both sentences, not two adjacent
  // "Speaker 2" headings.
  const { window, document } = buildWindow(getFixtureHtml('triple'));

  const bubble = document.querySelector('.bubble[data-line="0-0-2"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-0-2"]')).textContent, 'Speaker 2');
  assert.equal(headingBefore(document.querySelector('.plain-line[data-line="0-1-0"]')), null, 'merges into the section the override just opened');
  assert.equal(document.querySelectorAll('.plain-heading').length, 2, 'no duplicate "Speaker 2" heading');

  window.close();
});

test('editing a reassigned sentence\'s own plain line never bakes anything but its text into the card', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const bubble = document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  const bodyEl = document.querySelector('.plain-line[data-line="0-0-1"] .plain-body');
  // Simulate a correction typed into the line, leaving its leading
  // "{LRI}{n}{PDI}. {LRI}[range]{PDI} " lead-in untouched, the way a real
  // keystroke would.
  bodyEl.textContent = bodyEl.textContent.replace('עוד משפט קצר', 'עוד משפט מתוקן');
  bodyEl.dispatchEvent(new window.Event('input', { bubbles: true }));

  const card = document.querySelector('.bubble[data-line="0-0-1"] p');
  assert.equal(card.textContent, 'עוד משפט מתוקן');
  assert.ok(!card.textContent.includes('['), 'the card text must carry no bracket from the stripped lead-in');
  assert.ok(!card.textContent.includes(']'), 'the card text must carry no bracket from the stripped lead-in');

  window.close();
});
