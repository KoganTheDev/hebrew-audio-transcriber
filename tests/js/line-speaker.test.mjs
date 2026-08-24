// Behavioural coverage for per-bubble speaker overrides - the sentence-level
// counterpart to turn reassignment (see speakers.test.mjs) added for the "no
// feature loss" checklist's "Reassign speaker" row: the .spk chip only ever
// moves a whole cluster (up to 30s), so a single mislabelled sentence could
// not be fixed by hand at all until this control existed.
//
// state.assignLine[lineId] (js/00-preamble.js), reassignLine()/
// paintBubbleOverride()/applyLineAssignments() (js/24-speakers-menus.js) and
// the mixed-speaker plain-row prefix (js/32-plain-text.js's rowSpeakerName())
// are exercised here against the real rendered page, the same way every
// other *.test.mjs in this directory drives real markup rather than a
// hand-written stand-in - see harness.mjs's own module docstring.
//
// Fixture recap (render_fixture.py's "full" build): turn "0-0" is speaker 0
// ("Speaker 1") with two sentences - bubbles "0-0-0" and "0-0-1"; turn "0-1"
// is speaker 1 ("Speaker 2") with one sentence - bubble "0-1-0".

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

test('an override that makes a row agree with the row before it removes its own heading - the run merges', () => {
  // Turn "0-1" has exactly one sentence/bubble, so overriding it to speaker
  // 0 changes what EVERY bubble in the turn agrees on - the unambiguous
  // case rowSpeakerName() (js/32-plain-text.js) resolves by reporting the
  // overridden name directly, rather than falling back to the cluster's.
  // Speaker 0 ("Speaker 1") is ALSO turn "0-0"'s own speaker, so this
  // override makes two consecutive rows agree that did not before - proof
  // that heading visibility is recomputed across rows, after overrides,
  // not decided once per row in isolation (see rebuildPlain()'s own
  // comment in js/32-plain-text.js).
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const row00 = document.querySelector('.plain-row[data-turn="0-0"]');
  const row01 = document.querySelector('.plain-row[data-turn="0-1"]');
  assert.equal(row00.querySelector('.plain-heading').textContent, 'Speaker 1', 'the first row of a document always starts a run');
  assert.equal(row01.querySelector('.plain-heading').textContent, 'Speaker 2', 'before the override, row 0-1 starts its own run');

  const bubble = document.querySelector('.bubble[data-line="0-1-0"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="0"]'));

  assert.equal(row00.querySelector('.plain-heading').textContent, 'Speaker 1', 'unaffected - still the first row');
  assert.equal(row01.querySelector('.plain-heading'), null, 'row 0-1 now agrees with the row before it, so its heading is gone');

  window.close();
});

test('the plain-panel row falls back to the cluster\'s name and tags only the disagreeing line when a turn is genuinely mixed', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  // Turn "0-0" has two bubbles. Overriding only the second one to speaker 1
  // leaves the turn's two bubbles disagreeing with each other.
  const bubble = document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  const row = document.querySelector('.plain-row[data-turn="0-0"]');
  const heading = row.querySelector('.plain-heading').textContent;
  assert.ok(heading.includes('Speaker 1'), `expected the cluster's own name to remain the row heading, got: ${heading}`);

  const body = row.querySelector('.plain-body').textContent;
  assert.ok(body.includes('[Speaker 2]'), `expected the disagreeing line to carry its own bracketed tag, got: ${body}`);
  // The FIRST line (still agreeing with the cluster) must carry no override
  // tag - it may still legitimately carry its own "[start - end]" range
  // (the fixture renders with timestamps on), so the check is for the
  // override-tag's own bracketed-name shape specifically, not for the
  // absence of every bracket on the line.
  const firstLine = body.split('\n')[0];
  assert.ok(!/\[Speaker/.test(firstLine), `the untouched first line must carry no override tag, got: ${firstLine}`);

  window.close();
});

test('editing the plain panel of a mixed row never bakes the bracketed override tag into the card text', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const bubble = document.querySelector('.bubble[data-line="0-0-1"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  const row = document.querySelector('.plain-row[data-turn="0-0"]');
  const bodyEl = row.querySelector('.plain-body');
  // Simulate a correction typed into the (still-tagged) second line,
  // leaving its lead-in (number + bracketed name) untouched, the way a real
  // keystroke would.
  bodyEl.textContent = bodyEl.textContent.replace('עוד משפט קצר', 'עוד משפט מתוקן');
  bodyEl.dispatchEvent(new window.Event('input', { bubbles: true }));

  const card = document.querySelector('.bubble[data-line="0-0-1"] p');
  assert.equal(card.textContent, 'עוד משפט מתוקן');
  assert.ok(!card.textContent.includes('['), 'the card text must carry no bracket from the stripped override tag');
  assert.ok(!card.textContent.includes(']'), 'the card text must carry no bracket from the stripped override tag');

  window.close();
});
