// Behavioural coverage for runSearch()/focusMatch() (transcript.js): typing
// a query highlights matches, and Enter/Shift+Enter step through them.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function input(el, value) {
  el.value = value;
  el.dispatchEvent(new el.ownerDocument.defaultView.Event('input', { bubbles: true }));
}

function keydown(el, key, opts = {}) {
  el.dispatchEvent(new el.ownerDocument.defaultView.KeyboardEvent(
    'keydown', { key, bubbles: true, cancelable: true, ...opts }
  ));
}

// runSearch() is debounced 200ms behind the input's own 'input' listener
// (see bindChrome()) - real setTimeout, so tests await it rather than
// calling runSearch() directly (which is not exported from the IIFE, only
// reachable through the same DOM event a reader's typing fires).
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('typing a two-plus character query highlights every matching word', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const box = document.getElementById('search');

  // "שלום" appears in HE, the shared segment text every seg() in the
  // fixture carries (see render_fixture.py).
  input(box, 'שלום');
  await wait(300);

  const hits = document.querySelectorAll('mark.hit');
  assert.ok(hits.length >= 1, 'expected at least one highlighted match');

  window.close();
});

test('Enter moves to the next match and Shift+Enter to the previous one', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const box = document.getElementById('search');

  input(box, 'שלום');
  await wait(300);

  const hits = () => document.querySelectorAll('mark.hit');
  assert.ok(hits().length >= 2, 'this test needs at least two matches to prove stepping moves');

  const currentIndex = () => Array.prototype.findIndex.call(hits(), (m) => m.classList.contains('current'));
  const first = currentIndex();

  keydown(box, 'Enter');
  const afterNext = currentIndex();
  assert.notEqual(afterNext, first, 'Enter must move to a different match');

  keydown(box, 'Enter', { shiftKey: true });
  const afterPrev = currentIndex();
  assert.equal(afterPrev, first, 'Shift+Enter must move back to the previous match');

  window.close();
});

test('Escape in the search box clears the query and the highlights', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const box = document.getElementById('search');

  input(box, 'שלום');
  await wait(300);
  assert.ok(document.querySelectorAll('mark.hit').length >= 1);

  keydown(box, 'Escape');

  assert.equal(box.value, '');
  assert.equal(document.querySelectorAll('mark.hit').length, 0);

  window.close();
});

test('a query under two characters clears any previous search rather than matching everything', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const box = document.getElementById('search');

  input(box, 'שלום');
  await wait(300);
  assert.ok(document.querySelectorAll('mark.hit').length >= 1);

  input(box, 'ש');
  await wait(300);
  assert.equal(document.querySelectorAll('mark.hit').length, 0);

  window.close();
});
