// Behavioural coverage for bindEditing() (transcript.js): typing into a
// turn's contenteditable body marks it edited, drops any confidence
// shading, and autosaves to localStorage.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function typeInto(body, text) {
  body.textContent = '';
  const p = body.ownerDocument.createElement('p');
  p.textContent = text;
  body.appendChild(p);
  body.dispatchEvent(new body.ownerDocument.defaultView.Event('input', { bubbles: true }));
}

test('editing a turn marks it edited immediately', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  assert.notEqual(turn.dataset.edited, 'true');
  typeInto(body, 'a corrected line');

  assert.equal(turn.dataset.edited, 'true');

  window.close();
});

test('editing a turn autosaves the new text to localStorage', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  assert.equal(window.localStorage.getItem(key), null, 'nothing should be saved before any edit');

  typeInto(body, 'a corrected line');
  await wait(500);

  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.deepEqual(saved.turns['0-0'], ['a corrected line']);

  window.close();
});

test('editing a flagged turn removes its low-confidence shading', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  const flagsBtn = document.getElementById('toggle-flags');
  flagsBtn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  assert.ok(turn.querySelector('.lowconf'), 'expected the fixture\'s low-confidence word to be shaded once flags are on');

  const body = turn.querySelector('.body');
  typeInto(body, 'no more uncertainty here');

  assert.equal(turn.querySelector('.lowconf'), null, 'editing must clear the shading, not leave it describing stale text');

  window.close();
});
