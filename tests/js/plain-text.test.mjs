// Behavioural coverage for the plain-text panel's own timestamp/speaker
// toggles (rebuildPlain()/bindPlain() in transcript.js): checking .opt-spk
// changes whether the speaker name prefixes each row, and checking .opt-ts
// changes whether each SENTENCE LINE carries its own bracketed range - the
// range moved down from the row's own prefix to sit beside each sentence's
// number (see _render_plain_row_html()'s docstring in
// core/formatting/document.py, and numberedLines() in
// js/32-plain-text.js), because a turn can hold several sentences and one
// range on the row could not identify any single one of them. Both boxes
// render `checked` by default (see core/formatting/document.py's
// _render_plain_html()), so "default state" here means both the prefix name
// and every line's range are present, not absent.

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

test('both toggles render checked by default: the prefix carries the speaker name and every line carries its own range', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);
  const row = panel.querySelector('.plain-row[data-turn="0-0"]');

  assert.equal(panel.querySelector('.opt-ts').checked, true);
  assert.equal(panel.querySelector('.opt-spk').checked, true);
  const prefix = row.querySelector('.plain-prefix').textContent;
  assert.ok(!prefix.includes('['), 'the range no longer lives in the row prefix');
  assert.ok(prefix.includes('Speaker 1'), 'expected the speaker name in the default prefix');

  const body = row.querySelector('.plain-body').textContent;
  const lines = body.split('\n');
  assert.ok(lines.every((line) => line.includes('[')), 'expected every line to carry its own bracketed range');

  window.close();
});

test('unchecking the timestamp toggle drops every line\'s bracketed range but keeps the speaker name', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);

  const row = panel.querySelector('.plain-row[data-turn="0-0"]');
  const prefix = row.querySelector('.plain-prefix').textContent;
  assert.ok(prefix.includes('Speaker 1'), 'the speaker toggle was not touched, so its half must remain');

  const body = row.querySelector('.plain-body').textContent;
  const lines = body.split('\n');
  assert.ok(lines.every((line) => !line.includes('[')), 'expected the bracketed range to be gone from every line');

  window.close();
});

test('unchecking both toggles leaves the row with no prefix at all, and every line with no range', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);
  change(panel.querySelector('.opt-spk'), false);

  const row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.equal(row.querySelector('.plain-prefix').textContent, '');
  const body = row.querySelector('.plain-body').textContent;
  assert.ok(body.split('\n').every((line) => !line.includes('[')));

  window.close();
});

test('re-checking a toggle restores its half of the line lead-in', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);
  const tsBox = panel.querySelector('.opt-ts');

  change(tsBox, false);
  let row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.ok(!row.querySelector('.plain-body').textContent.includes('['));

  change(tsBox, true);
  row = panel.querySelector('.plain-row[data-turn="0-0"]');
  assert.ok(row.querySelector('.plain-body').textContent.includes('['));

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
