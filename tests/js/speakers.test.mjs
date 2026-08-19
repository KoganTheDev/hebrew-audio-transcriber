// Behavioural coverage for speaker renaming (bindSpeakerRow()/applyNames())
// and turn reassignment (buildSpeakerMenu()/reassignTurn()) in
// transcript.js.

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

test('renaming a speaker in the sidebar repaints every .spk chip for that speaker', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const row = document.querySelector('.speakers[data-file="0"] .speaker-row[data-speaker="0"]');
  const nameInput = row.querySelector('.speaker-name');
  input(nameInput, 'Alice');

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  assert.equal(turn.querySelector('.spk').textContent, 'Alice');

  // The other speaker in the same file must be unaffected.
  const otherTurn = document.querySelector('.turn[data-turn="0-1"]');
  assert.notEqual(otherTurn.querySelector('.spk').textContent, 'Alice');

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

  const otherTurn = document.querySelector('.turn[data-turn="1-0"]');
  assert.equal(otherTurn.querySelector('.spk').textContent, 'Alice');

  window.close();
});

test('clicking a turn\'s speaker chip opens a reassignment menu listing every speaker in that file', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  click(turn.querySelector('.spk'));

  const menu = document.querySelector('.spk-menu');
  assert.ok(menu, 'expected a reassignment menu to open');
  assert.equal(menu.querySelectorAll('.spk-menu-item').length, 2, 'file 0 has two speakers');

  window.close();
});

test('choosing a different speaker in the reassignment menu moves the turn to it', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  assert.equal(turn.dataset.speaker, '0');

  click(turn.querySelector('.spk'));
  const item = document.querySelector('.spk-menu-item[data-speaker="1"]');
  assert.ok(item);
  click(item);

  assert.equal(turn.dataset.speaker, '1');
  assert.equal(turn.querySelector('.spk').dataset.speaker, '1');
  // The menu must close as part of the reassignment, not linger open on a
  // now-stale roster.
  assert.equal(document.querySelector('.spk-menu'), null);

  window.close();
});

test('a reassignment autosaves the new assignment', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  click(turn.querySelector('.spk'));
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  await new Promise((resolve) => setTimeout(resolve, 500));

  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.equal(saved.assign['0-0'], 1);

  window.close();
});
