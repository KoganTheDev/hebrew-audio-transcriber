// Behavioural coverage for speaker renaming (bindSpeakerRow()/applyNames())
// and whole-block reassignment (buildSpeakerMenu()/reassignTurn()) in
// transcript.js. The trigger is a card's own .bubble-spk chip now, with the
// menu's own scope group choosing between "this sentence" (reassignLine())
// and "this whole block" (reassignTurn()) - there is no more cluster-header
// .spk to click at all, see the review plan's "flat sentence cards" section
// for why. This file drives the "whole block" scope specifically;
// line-speaker.test.mjs covers the (default) "this sentence" scope.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function input(el, value) {
  el.value = value;
  el.dispatchEvent(new el.ownerDocument.defaultView.Event('input', { bubbles: true }));
}

// Opens turn 0-0's first bubble's reassignment menu and selects the "This
// whole block" scope item, leaving the menu open with that scope active -
// the shared first half of every whole-block test below.
function openBlockScopeMenu(document, lineId) {
  const bubble = document.querySelector(`.bubble[data-line="${lineId}"]`);
  click(bubble.querySelector('.bubble-spk'));
  const blockItem = document.querySelector('.spk-scope-item[data-scope="block"]');
  assert.ok(blockItem, 'expected a "this whole block" scope item in the menu');
  click(blockItem);
  return bubble;
}

test('renaming a speaker in the sidebar repaints every .bubble-spk chip for that speaker', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const row = document.querySelector('.speakers[data-file="0"] .speaker-row[data-speaker="0"]');
  const nameInput = row.querySelector('.speaker-name');
  input(nameInput, 'Alice');

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  assert.equal(bubble.querySelector('.bubble-spk-label').textContent, 'Alice');

  // The other speaker in the same file must be unaffected.
  const otherBubble = document.querySelector('.bubble[data-line="0-1-0"]');
  assert.notEqual(otherBubble.querySelector('.bubble-spk-label').textContent, 'Alice');

  window.close();
});

test('a rename does not leak into a different file\'s speaker roster', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const row = document.querySelector('.speakers[data-file="0"] .speaker-row[data-speaker="0"]');
  input(row.querySelector('.speaker-name'), 'Alice');

  const otherFileInput = document.querySelector('.speakers[data-file="1"] .speaker-row[data-speaker="0"] .speaker-name');
  assert.notEqual(otherFileInput.value, 'Alice');

  window.close();
});

test('"use these names in all files" applies file 0\'s names to every other file\'s matching speaker', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  input(document.querySelector('.speakers[data-file="0"] .speaker-row[data-speaker="0"] .speaker-name'), 'Alice');
  click(document.querySelector('.speakers[data-file="0"] .apply-all'));

  const otherFileInput = document.querySelector('.speakers[data-file="1"] .speaker-row[data-speaker="0"] .speaker-name');
  assert.equal(otherFileInput.value, 'Alice');

  const otherBubble = document.querySelector('.bubble[data-line="1-0-0"]');
  assert.equal(otherBubble.querySelector('.bubble-spk-label').textContent, 'Alice');

  window.close();
});

test('clicking a card\'s speaker chip opens a reassignment menu listing every speaker in that file', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  click(bubble.querySelector('.bubble-spk'));

  const menu = document.querySelector('.spk-menu');
  assert.ok(menu, 'expected a reassignment menu to open');
  assert.equal(menu.querySelectorAll('.spk-menu-item').length, 2, 'file 0 has two speakers');
  // The scope group is its own, separate set of items - "this sentence" /
  // "this whole block" - not counted as speakers.
  assert.equal(menu.querySelectorAll('.spk-scope-item').length, 2);
  assert.equal(
    menu.querySelector('.spk-scope-item[data-scope="line"]').getAttribute('aria-checked'), 'true',
    'the menu opens with "this sentence" selected by default'
  );

  window.close();
});

test('choosing "this whole block" then a different speaker moves every un-overridden bubble in the block', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  assert.equal(turn.dataset.speaker, '0');

  const bubble = openBlockScopeMenu(document, '0-0-0');
  const item = document.querySelector('.spk-menu-item[data-speaker="1"]');
  assert.ok(item);
  click(item);

  assert.equal(turn.dataset.speaker, '1');
  assert.equal(bubble.dataset.speaker, '1');
  assert.equal(bubble.querySelector('.bubble-spk').dataset.speaker, '1');
  // The turn's OTHER bubble, which was never given its own override, must
  // move along with the block too.
  const sibling = document.querySelector('.bubble[data-line="0-0-1"]');
  assert.equal(sibling.dataset.speaker, '1');
  // The menu must close as part of the reassignment, not linger open on a
  // now-stale roster.
  assert.equal(document.querySelector('.spk-menu'), null);

  window.close();
});

test('choosing "this whole block" leaves an already-overridden sibling bubble alone', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  // Override the turn's second bubble to speaker 1 first.
  const second = document.querySelector('.bubble[data-line="0-0-1"]');
  click(second.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));
  assert.equal(second.dataset.override, 'true');

  // Now reassign the whole block to a speaker neither bubble currently is.
  openBlockScopeMenu(document, '0-0-0');
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  const first = document.querySelector('.bubble[data-line="0-0-0"]');
  assert.equal(first.dataset.speaker, '1', 'the un-overridden bubble follows the block');
  // The overridden sibling keeps its own opinion - a block reassignment is
  // not the same action as clearing every sentence's own override.
  assert.equal(second.dataset.override, 'true');
  assert.equal(second.dataset.speaker, '1');

  window.close();
});

test('a whole-block reassignment autosaves the new assignment', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;

  openBlockScopeMenu(document, '0-0-0');
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  await new Promise((resolve) => setTimeout(resolve, 500));

  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.equal(saved.assign['0-0'], 1);
  // A block reassignment must not also write a redundant per-line override
  // for the bubble whose menu happened to trigger it.
  assert.equal(Object.prototype.hasOwnProperty.call(saved.assignLine, '0-0-0'), false);

  window.close();
});
