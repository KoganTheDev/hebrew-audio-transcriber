// Behavioural coverage for the unattributed speaker chip - the card
// speaker_attribution.py could not place (speaker=None, because no
// diarization span overlapped it or the gap was too wide to borrow a
// neighbour's label across).
//
// This used to render NO chip at all, which was worse than cosmetic: the
// reassignment menu only opens from a .bubble-spk (bindMenus() in
// js/24-speakers-menus.js), so a card with no chip had no trigger and could
// not be corrected by hand at all, and paintBubbleOverride() bailed out on
// its missing button so even a saved override silently no-opped. These tests
// pin the chip's existence, its menu, and the round trip back to the
// unattributed resting state.
//
// Fixture recap (render_fixture.py's "unattributed" build): one file, three
// turns - "0-0" is speaker 0 ("Speaker 1"), "0-1" has NO speaker, "0-2" is
// speaker 1 ("Speaker 2"). The roster therefore has two real speakers for
// the unattributed card to be reassigned to.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('a turn with no speaker still renders a chip, marked unattributed rather than as speaker 0', () => {
  const { window, document } = buildWindow(getFixtureHtml('unattributed'));

  const bubble = document.querySelector('.bubble[data-line="0-1-0"]');
  assert.ok(bubble, 'expected the unattributed turn to render a bubble');

  const chip = bubble.querySelector('.bubble-spk');
  assert.ok(chip, 'an unattributed card must still carry a chip - it is the only reassignment trigger');

  // The distinction that matters: absent identity, not identity 0. A
  // data-speaker="0" here would both colour it as the first speaker and make
  // every "is this bubble speaker N" comparison silently true.
  assert.equal(chip.hasAttribute('data-speaker'), false);
  assert.equal(chip.hasAttribute('data-palette'), false);
  assert.equal(chip.getAttribute('data-unattributed'), 'true');
  assert.equal(bubble.getAttribute('data-unattributed'), 'true');

  // Attributed neighbours are unaffected.
  const attributed = document.querySelector('.bubble[data-line="0-0-0"] .bubble-spk');
  assert.equal(attributed.dataset.speaker, '0');
  assert.equal(attributed.hasAttribute('data-unattributed'), false);

  window.close();
});

test('the unattributed chip opens the reassignment menu with no speaker pre-checked', () => {
  const { window, document } = buildWindow(getFixtureHtml('unattributed'));

  click(document.querySelector('.bubble[data-line="0-1-0"] .bubble-spk'));

  const menu = document.querySelector('.spk-menu');
  assert.ok(menu, 'expected the menu to open from an unattributed chip');
  assert.equal(menu.querySelectorAll('.spk-menu-item').length, 2, 'the file has two real speakers');
  // Nothing is checked: the card genuinely has no speaker yet, so
  // pre-selecting one would assert an attribution the pipeline refused to
  // make.
  assert.equal(menu.querySelector('.spk-menu-item[aria-checked="true"]'), null);

  window.close();
});

test('assigning a speaker to an unattributed card paints it and persists across a reload', async () => {
  const seedKey = 'hebrew-transcript:js-fixture-unattributed';
  const first = buildWindow(getFixtureHtml('unattributed'));

  const bubble = first.document.querySelector('.bubble[data-line="0-1-0"]');
  click(bubble.querySelector('.bubble-spk'));
  const item = first.document.querySelector('.spk-menu .spk-menu-item[data-speaker="1"]');
  click(item);

  const chip = first.document.querySelector('.bubble[data-line="0-1-0"] .bubble-spk');
  assert.equal(chip.dataset.speaker, '1', 'the chip should now carry a real identity');
  assert.equal(chip.hasAttribute('data-unattributed'), false, 'and must drop the unattributed marker');
  assert.equal(chip.dataset.palette, '1');
  assert.equal(
    first.document.querySelector('.bubble[data-line="0-1-0"]').hasAttribute('data-unattributed'),
    false,
    'the card itself carries the marker too, so it must be cleared in both places or the '
      + '[data-unattributed] rule keeps overriding --spk',
  );

  // save() is debounced (js/08-storage.js) - wait past it before reading
  // storage back, the same way the other persistence tests here do.
  await wait(600);
  const saved = first.window.localStorage.getItem(seedKey);
  assert.ok(saved, 'expected the assignment to be written to localStorage');
  assert.equal(JSON.parse(saved).assignLine['0-1-0'], 1);
  first.window.close();

  // Each jsdom instance gets its own storage area, so a reload has to be
  // simulated by seeding the saved state into a fresh window.
  const second = buildWindow(getFixtureHtml('unattributed'), { [seedKey]: saved });
  const reloaded = second.document.querySelector('.bubble[data-line="0-1-0"] .bubble-spk');
  assert.equal(reloaded.dataset.speaker, '1', 'the assignment must survive a reload');
  assert.equal(reloaded.hasAttribute('data-unattributed'), false);
  second.window.close();
});

test('clearing the override returns the card to the unattributed state, not to a blank chip', () => {
  const { window, document } = buildWindow(getFixtureHtml('unattributed'));

  const line = '.bubble[data-line="0-1-0"]';
  click(document.querySelector(`${line} .bubble-spk`));
  click(document.querySelector('.spk-menu .spk-menu-item[data-speaker="1"]'));
  assert.equal(document.querySelector(`${line} .bubble-spk`).dataset.speaker, '1');

  // Choosing the SAME speaker again clears the override (see reassignLine()).
  click(document.querySelector(`${line} .bubble-spk`));
  click(document.querySelector('.spk-menu .spk-menu-item[data-speaker="1"]'));

  const chip = document.querySelector(`${line} .bubble-spk`);
  assert.equal(chip.getAttribute('data-unattributed'), 'true', 'should fall back to unattributed');
  assert.equal(chip.hasAttribute('data-speaker'), false);
  // The label has to come back too - the chip's data-fallback was overwritten
  // with a real speaker's name while the override was set, and an empty chip
  // is explicitly not a valid resting state.
  assert.notEqual(chip.querySelector('.bubble-spk-label').textContent.trim(), '');

  window.close();
});
