// Behavioural coverage for the plain-text panel's own timestamp/speaker
// toggles (rebuildPlain()/bindPlain() in transcript.js): checking .opt-ts
// or .opt-spk changes whether the bracketed range / speaker name prefixes
// each row. Both boxes render `checked` by default (see
// core/formatting/document.py's _render_plain_html()), so "default state"
// here means both prefixes present, not absent.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function change(el, checked) {
  el.checked = checked;
  el.dispatchEvent(new el.ownerDocument.defaultView.Event('change', { bubbles: true }));
}

function panelForFile0(document) {
  return document.querySelector('.source[data-file="0"] .plain');
}

test('both toggles render checked by default and rows carry both prefixes', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);
  const row = panel.querySelector('.plain-row[data-turn="0-0"]');

  assert.equal(panel.querySelector('.opt-ts').checked, true);
  assert.equal(panel.querySelector('.opt-spk').checked, true);
  const prefix = row.querySelector('.plain-prefix').textContent;
  assert.ok(prefix.includes('['), 'expected a bracketed timestamp in the default prefix');
  assert.ok(prefix.includes('Speaker 1'), 'expected the speaker name in the default prefix');

  window.close();
});

test('unchecking the timestamp toggle drops the bracketed range but keeps the speaker name', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);

  const row = panel.querySelector('.plain-row[data-turn="0-0"]');
  const prefix = row.querySelector('.plain-prefix').textContent;
  assert.ok(!prefix.includes('['), 'expected the bracketed timestamp to be gone');
  assert.ok(prefix.includes('Speaker 1'), 'the speaker toggle was not touched, so its half must remain');

  window.close();
});

test('unchecking both toggles leaves the row with no prefix at all', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);
  change(panel.querySelector('.opt-spk'), false);

  const row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.equal(row.querySelector('.plain-prefix').textContent, '');

  window.close();
});

test('re-checking a toggle restores its half of the prefix', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);
  const tsBox = panel.querySelector('.opt-ts');

  change(tsBox, false);
  let row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.ok(!row.querySelector('.plain-prefix').textContent.includes('['));

  change(tsBox, true);
  row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.ok(row.querySelector('.plain-prefix').textContent.includes('['));

  window.close();
});

test('toggle state autosaves per file', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);
  await new Promise((resolve) => setTimeout(resolve, 500));

  const saved = JSON.parse(window.localStorage.getItem(key));
  assert.equal(saved.opts['0'].ts, false);
  assert.equal(saved.opts['0'].spk, true, 'the speaker box was not touched and is checked by default');

  window.close();
});
