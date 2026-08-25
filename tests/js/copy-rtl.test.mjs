// Copied text has to survive leaving the browser.
//
// Inside the page the document is dir="rtl" and paragraph direction is
// settled. In the clipboard it is not: apps that guess direction use a
// paragraph's FIRST STRONG character, and every plain-text line now opens
// with the sentence number - an LTR run inside an isolate. Without an
// anchor, Word/Notepad/chat apps left-align the whole Hebrew paragraph.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

const RLM = '\u200f';
const LRI = '\u2066';

function firstStrongIsRtl(line) {
  // Mirrors what a receiving app does: scan for the first character with a
  // strong direction, skipping isolates/marks that carry none of their own.
  for (const ch of line) {
    const c = ch.codePointAt(0);
    if (c === 0x200f) { return true; }               // RLM, strong RTL
    if (c >= 0x0590 && c <= 0x08ff) { return true; } // Hebrew/Arabic block
    if ((c >= 0x41 && c <= 0x5a) || (c >= 0x61 && c <= 0x7a)) { return false; }
  }
  return false;
}

test('copied plain text anchors every line right-to-left', async () => {
  const { window } = await buildWindow(await getFixtureHtml('full'));
  const copied = [];
  window.navigator.clipboard = { writeText: (t) => { copied.push(t); return Promise.resolve(); } };

  window.document.querySelector('.plain .copy-all').click();
  assert.equal(copied.length, 1, 'copy-all should have written to the clipboard');

  const lines = copied[0].split('\n').filter((l) => l.trim().length);
  assert.ok(lines.length >= 2, 'need several lines to be meaningful');
  for (const line of lines) {
    assert.ok(line.startsWith(RLM), `line not anchored: ${JSON.stringify(line.slice(0, 24))}`);
    assert.ok(firstStrongIsRtl(line), `first strong char is LTR: ${JSON.stringify(line.slice(0, 24))}`);
  }
  // The anchor must not have displaced the numbering it protects.
  assert.ok(lines.some((l) => l.includes(LRI + '1')), 'sentence numbers should survive');
});

test('copying a single card anchors it too', async () => {
  const { window } = await buildWindow(await getFixtureHtml('full'));
  const copied = [];
  window.navigator.clipboard = { writeText: (t) => { copied.push(t); return Promise.resolve(); } };

  const btn = window.document.querySelector('.bubble .copy-line');
  if (!btn) { return; }
  btn.click();
  assert.equal(copied.length, 1);
  assert.ok(copied[0].startsWith(RLM), JSON.stringify(copied[0].slice(0, 24)));
});
