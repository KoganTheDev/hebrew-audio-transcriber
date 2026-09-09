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

test('a browser that refuses to save says so out loud, once', async () => {
  // localStorage throws when the quota is full, and Chrome pools every file://
  // document into a single origin - so this page shares a few megabytes with
  // every transcript ever opened on the machine, and nothing evicts the old
  // ones. Before this, the only sign was the status box swapping one
  // pre-rendered label for another in a corner, while the reader was looking
  // at the text they were editing. An afternoon of proofreading could be lost
  // to a colour change.
  const { window, document } = buildWindow(getFixtureHtml('full'));

  // Overridden on Storage.prototype, not on the localStorage instance. jsdom
  // proxies the instance, so both a plain assignment and defineProperty on it
  // are silently ignored and the real implementation still runs - a stub that
  // quietly does nothing would make this test pass against the bug.
  Object.defineProperty(window.Storage.prototype, 'setItem', {
    configurable: true,
    value: () => {
      const err = new Error('quota');
      err.name = 'QuotaExceededError';
      throw err;
    },
  });

  const body = document.querySelector('.turn[data-turn="0-0"] .body');
  body.dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(600);

  const toast = document.getElementById('toast');
  assert.equal(toast.hidden, false, 'a failed save must be announced, not just recoloured');
  assert.match(toast.textContent, /Save a copy|שמירת עותק/,
    'the warning has to name the way out, not merely report the failure');

  const status = document.getElementById('status');
  assert.equal(status.dataset.kind, 'error', 'the status box still reports the failure too');

  window.close();
});

test('a browser that refuses to save does not nag on every keystroke', async () => {
  // save() is debounced but still fires per pause, and a full quota stays
  // full - so without a guard the toast would reappear for the rest of the
  // session, on top of the text being edited.
  const { window, document } = buildWindow(getFixtureHtml('full'));

  Object.defineProperty(window.Storage.prototype, 'setItem', {
    configurable: true,
    value: () => { throw new Error('quota'); },
  });

  let shown = 0;
  const toast = document.getElementById('toast');
  const obs = new window.MutationObserver((records) => {
    records.forEach((r) => {
      if (r.attributeName === 'hidden' && toast.hidden === false) { shown++; }
    });
  });
  obs.observe(toast, { attributes: true });

  const body = document.querySelector('.turn[data-turn="0-0"] .body');
  for (let i = 0; i < 3; i++) {
    body.dispatchEvent(new window.Event('input', { bubbles: true }));
    await wait(500);
  }

  assert.equal(shown, 1, `expected the warning once, got it ${shown} times`);

  window.close();
});
