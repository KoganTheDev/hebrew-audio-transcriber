// Behavioural coverage for the plain-text panel's own timestamp/speaker
// toggles (rebuildPlain()/bindPlain() in transcript.js): checking .opt-spk
// changes whether a speaker heading renders above a run of .plain-line
// elements, and checking .opt-ts changes whether each SENTENCE LINE carries
// its own bracketed range - the range sits beside each sentence's own
// number (see _render_plain_html()'s docstring in core/formatting/
// document.py, and rebuildPlain()'s lineLeadIn() in js/32-plain-text.js),
// because a turn can hold several sentences and one range on a shared row
// could not identify any single one of them. Both boxes render `checked` by
// default (see core/formatting/document.py's _render_plain_html()), so
// "default state" here means both the heading and every line's range are
// present, not absent. Turn "0-0"'s first sentence ("0-0-0") is the
// fixture's FIRST sentence, so its heading always renders regardless of the
// run logic (see _render_plain_html()'s docstring for why the first line of
// a document always starts a run) - heading-per-run itself is covered by
// line-speaker.test.mjs instead.

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

test('both toggles render checked by default: the heading shows the speaker name and every line carries its own range', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  assert.equal(panel.querySelector('.opt-ts').checked, true);
  assert.equal(panel.querySelector('.opt-spk').checked, true);

  const heading = panel.querySelector('.plain-heading');
  assert.ok(heading, 'expected a heading on the first line of the document');
  assert.equal(heading.textContent, 'Speaker 1');
  // The heading must precede the first line of its run in the DOM.
  const firstLine = panel.querySelector('.plain-line[data-line="0-0-0"]');
  assert.equal(heading.nextElementSibling, firstLine);

  const lines = panel.querySelectorAll('.plain-line .plain-body');
  assert.ok(lines.length > 0, 'expected at least one line');
  lines.forEach((line) => {
    assert.ok(line.textContent.includes('['), `expected every line to carry its own bracketed range, got: ${line.textContent}`);
  });

  window.close();
});

test('unchecking the timestamp toggle drops every line\'s bracketed range but keeps the heading', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);

  assert.equal(panel.querySelector('.plain-heading').textContent, 'Speaker 1', 'the speaker toggle was not touched, so its half must remain');

  const lines = panel.querySelectorAll('.plain-line .plain-body');
  assert.ok(lines.length > 0);
  lines.forEach((line) => {
    assert.ok(!line.textContent.includes('['), `expected the bracketed range to be gone, got: ${line.textContent}`);
  });

  window.close();
});

test('unchecking both toggles leaves the panel with no heading at all, and every line with no range', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);

  change(panel.querySelector('.opt-ts'), false);
  change(panel.querySelector('.opt-spk'), false);

  assert.equal(panel.querySelector('.plain-heading'), null);
  const lines = panel.querySelectorAll('.plain-line .plain-body');
  assert.ok(lines.length > 0);
  lines.forEach((line) => {
    assert.ok(!line.textContent.includes('['));
  });

  window.close();
});

test('re-checking a toggle restores its half of the line lead-in', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const panel = panelForFile0(document);
  const tsBox = panel.querySelector('.opt-ts');

  change(tsBox, false);
  let line = panel.querySelector('.plain-line[data-line="0-0-0"] .plain-body');
  assert.ok(!line.textContent.includes('['));

  change(tsBox, true);
  line = panel.querySelector('.plain-line[data-line="0-0-0"] .plain-body');
  assert.ok(line.textContent.includes('['));

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
