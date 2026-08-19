// Behavioural coverage for the theme toggle (bindChrome()/effectiveTheme()/
// syncThemeLabel() in transcript.js): clicking it flips data-theme and
// persists the choice to localStorage under this document's own key.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

// save() debounces the actual localStorage.setItem 400ms behind the change
// (see its own comment: "a fast typist writes once per pause, not once per
// keystroke") - real setTimeout, so this waits it out rather than reading
// storage synchronously right after the click.
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('clicking the theme toggle flips document.documentElement.dataset.theme', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const before = document.documentElement.dataset.theme;

  click(document.getElementById('toggle-theme'));

  const after = document.documentElement.dataset.theme;
  assert.notEqual(after, before);
  assert.ok(after === 'dark' || after === 'light');

  window.close();
});

test('the theme choice is persisted to localStorage under this document key', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;

  click(document.getElementById('toggle-theme'));
  const chosen = document.documentElement.dataset.theme;
  await wait(500);

  const raw = window.localStorage.getItem(key);
  assert.ok(raw, 'expected an autosave entry after toggling the theme');
  const saved = JSON.parse(raw);
  assert.equal(saved.theme, chosen);

  window.close();
});

test('a second click toggles back to the other theme', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const toggle = document.getElementById('toggle-theme');

  click(toggle);
  const first = document.documentElement.dataset.theme;
  click(toggle);
  const second = document.documentElement.dataset.theme;

  assert.notEqual(first, second);

  window.close();
});
