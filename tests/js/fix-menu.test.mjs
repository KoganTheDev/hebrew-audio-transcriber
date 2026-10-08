// Behavioural coverage for click-to-fix (js/42-fix-menu.js, with
// renderTurn() in js/40-low-confidence.js): uncertain words are highlighted
// by default, clicking one opens a menu of fixes, and a pick changes that one
// word without touching the card's other highlights or marking it edited.
//
// Fixture "fixable" (render_fixture.py), turn 0-0:
//   "נסענו לקיסריה עם שרן ועם שרן נדחה."
//   לקיסריה - auto-corrected from לכיסריה
//   שרן     - doubted at occurrence 0 only, suggestions שרון / שירן
//   נדחה.   - doubted, no suggestions
// turn 0-1: "שלום עולם", עולם doubted.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

const KEY = 'hebrew-transcript:js-fixture-fixable';

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function click(node) {
  const win = node.ownerDocument.defaultView;
  node.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
}

function key(node, k) {
  const win = node.ownerDocument.defaultView;
  node.dispatchEvent(new win.KeyboardEvent('keydown', { key: k, bubbles: true }));
}

function flagged(document, turnId = '0-0') {
  return Array.from(document.querySelectorAll(`.turn[data-turn="${turnId}"] .lowconf`))
    .map((s) => s.textContent);
}

function cardText(document, turnId = '0-0') {
  return document.querySelector(`.turn[data-turn="${turnId}"] .body p`).textContent;
}

function word(document, text) {
  return Array.from(document.querySelectorAll('.lowconf')).find((s) => s.textContent === text);
}

function open(document, text) {
  click(word(document, text));
  return document.querySelector('.fix-menu');
}

test('uncertain words are highlighted without touching the toolbar', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  assert.deepEqual(flagged(document), ['לקיסריה', 'שרן', 'נדחה.']);
  assert.deepEqual(flagged(document, '0-1'), ['עולם']);
  assert.equal(document.getElementById('toggle-flags').getAttribute('aria-pressed'), 'true');

  window.close();
});

test('a reader who turned highlighting off keeps it off', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'), {
    [KEY]: JSON.stringify({ flags: false }),
  });

  assert.deepEqual(flagged(document), []);

  window.close();
});

test('only the doubted occurrence of a repeated word is highlighted', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const spans = document.querySelectorAll('.turn[data-turn="0-0"] .lowconf');
  const sharan = Array.from(spans).filter((s) => s.textContent === 'שרן');
  assert.equal(sharan.length, 1, 'the confident second שרן must stay plain');
  assert.equal(sharan[0].dataset.occ, '0');

  window.close();
});

test('an auto-corrected word is marked differently from a merely doubted one', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  assert.ok(word(document, 'לקיסריה').classList.contains('autofixed'));
  assert.ok(!word(document, 'שרן').classList.contains('autofixed'));

  window.close();
});

test('an uncertain word is a keyboard-reachable control', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const span = word(document, 'שרן');
  assert.equal(span.getAttribute('role'), 'button');
  assert.equal(span.getAttribute('tabindex'), '0');
  assert.equal(span.getAttribute('aria-haspopup'), 'menu');
  assert.equal(span.getAttribute('contenteditable'), 'false');

  span.focus();
  key(span, 'Enter');
  assert.ok(document.querySelector('.fix-menu'), 'Enter on a focused word opens its menu');

  window.close();
});

test('the menu offers the suggestions with key caps, another word, and keep', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const menu = open(document, 'שרן');
  const items = Array.from(menu.querySelectorAll('.fix-item')).map((b) => b.textContent);
  assert.ok(items[0].startsWith('שרון') && items[0].endsWith('1'));
  assert.ok(items[1].startsWith('שירן') && items[1].endsWith('2'));
  assert.ok(menu.querySelector('.fix-other input'));
  assert.ok(menu.querySelector('.fix-quiet'), 'keep as is');
  assert.equal(menu.querySelectorAll('kbd.fix-key').length, 2);
  assert.match(menu.querySelector('.fix-head').textContent, /40%/);
  // Icons come from the page's sprite, never a typed glyph.
  assert.ok(menu.querySelector('.fix-quiet svg use[href="#i-check"]'));
  assert.ok(menu.querySelector('.fix-other svg use[href="#i-edit"]'));

  window.close();
});

test('picking a suggestion changes that word and nothing else', async () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');

  click(open(document, 'שרן').querySelector('.fix-item'));

  assert.equal(cardText(document), 'נסענו לקיסריה עם שרון ועם שרן נדחה.');
  assert.deepEqual(flagged(document), ['לקיסריה', 'נדחה.'],
    'the other uncertain words in the same card stay highlighted');
  assert.deepEqual(flagged(document, '0-1'), ['עולם']);
  assert.notEqual(turn.dataset.edited, 'true', 'a pick is not an edit');
  assert.equal(document.querySelector('.fix-menu'), null);

  await wait(500);
  const saved = JSON.parse(window.localStorage.getItem(KEY));
  assert.deepEqual(saved.picks, { '0-0': { 'שרן#0': 'שרון' } });
  assert.equal(saved.turns['0-0'], undefined, 'nothing is stored as a typed edit');

  window.close();
});

test('a number key picks that suggestion', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const menu = open(document, 'שרן');
  key(menu.querySelector('.fix-item'), '2');

  assert.equal(cardText(document), 'נסענו לקיסריה עם שירן ועם שרן נדחה.');

  window.close();
});

test('keep as is removes the highlight and leaves the word', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  click(open(document, 'נדחה.').querySelector('.fix-quiet'));

  assert.equal(cardText(document), 'נסענו לקיסריה עם שרן ועם שרן נדחה.');
  assert.deepEqual(flagged(document), ['לקיסריה', 'שרן']);

  window.close();
});

test('another word typed in the field replaces it and keeps its punctuation', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const input = open(document, 'נדחה.').querySelector('.fix-other input');
  input.value = 'נדחה לחמישי';
  key(input, 'Enter');

  assert.equal(cardText(document), 'נסענו לקיסריה עם שרן ועם שרן נדחה לחמישי.');

  window.close();
});

test('an auto-corrected word offers its original back', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const menu = open(document, 'לקיסריה');
  assert.match(menu.querySelector('.fix-head').textContent, /לכיסריה/);
  const restore = menu.querySelector('.fix-restore');
  assert.ok(restore.querySelector('svg use[href="#i-undo"]'));
  click(restore);

  assert.equal(cardText(document), 'נסענו לכיסריה עם שרן ועם שרן נדחה.');

  window.close();
});

test('picks are applied again on reload, before the plain-text panel is built', async () => {
  const first = buildWindow(getFixtureHtml('fixable'));
  click(open(first.document, 'שרן').querySelector('.fix-item'));
  click(open(first.document, 'נדחה.').querySelector('.fix-quiet'));
  await wait(500);
  const saved = first.window.localStorage.getItem(KEY);
  first.window.close();

  const { window, document } = buildWindow(getFixtureHtml('fixable'), { [KEY]: saved });
  assert.equal(cardText(document), 'נסענו לקיסריה עם שרון ועם שרן נדחה.');
  assert.deepEqual(flagged(document), ['לקיסריה']);
  const plain = document.querySelector('.source[data-file="0"] .plain').textContent;
  assert.ok(plain.includes('שרון'), 'the plain-text panel carries the pick');

  window.close();
});

test('picks still apply with highlighting off', () => {
  const first = buildWindow(getFixtureHtml('fixable'));
  click(open(first.document, 'שרן').querySelector('.fix-item'));
  click(first.document.getElementById('toggle-flags'));

  assert.deepEqual(flagged(first.document), []);
  assert.equal(cardText(first.document), 'נסענו לקיסריה עם שרון ועם שרן נדחה.');

  click(first.document.getElementById('toggle-flags'));
  assert.deepEqual(flagged(first.document), ['לקיסריה', 'נדחה.'],
    'turning highlighting back on does not resurrect the picked word');

  first.window.close();
});

test('typing in a card still turns it into plain edited text', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  click(open(document, 'שרן').querySelector('.fix-item'));

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');
  body.dispatchEvent(new window.Event('input', { bubbles: true }));

  assert.equal(turn.dataset.edited, 'true');
  assert.equal(turn.querySelector('.lowconf, .picked'), null);
  assert.equal(cardText(document), 'נסענו לקיסריה עם שרון ועם שרן נדחה.');

  window.close();
});

test('Escape closes the menu and returns focus to the word', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  const span = word(document, 'שרן');
  const menu = open(document, 'שרן');
  key(menu.querySelector('.fix-item'), 'Escape');

  assert.equal(document.querySelector('.fix-menu'), null);
  assert.equal(document.activeElement, span);
  assert.equal(span.getAttribute('aria-expanded'), 'false');

  window.close();
});

test('a click elsewhere closes the menu without choosing', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));

  open(document, 'שרן');
  click(document.querySelector('.file-bar') || document.body);

  assert.equal(document.querySelector('.fix-menu'), null);
  assert.deepEqual(flagged(document), ['לקיסריה', 'שרן', 'נדחה.']);

  window.close();
});

test('the menu opens below the word, aligned to its start edge', () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  const span = word(document, 'שרן');
  span.getBoundingClientRect = () => ({ top: 100, bottom: 120, left: 300, right: 340, width: 40, height: 20 });

  const menu = open(document, 'שרן');

  assert.equal(menu.style.top, '126px', 'six pixels under the word, never above it');

  window.close();
});

test('an exported copy carries the pick as plain text, not a marker', async () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  click(open(document, 'שרן').querySelector('.fix-item'));

  const writes = [];
  window.showSaveFilePicker = () => Promise.resolve({
    createWritable() {
      return Promise.resolve({
        write(html) { writes.push(html); return Promise.resolve(); },
        close() { return Promise.resolve(); },
      });
    },
  });
  click(document.getElementById('export'));
  await wait(50);

  assert.equal(writes.length, 1);
  assert.ok(writes[0].includes('עם שרון ועם'), 'the picked word is in the copy');
  assert.ok(!writes[0].includes('class="picked"'), 'no pick marker leaks into the copy');
  assert.ok(document.querySelector('.picked'), 'the live page keeps its marker');

  window.close();
});

test('a resize keeps the menu open beside its word', () => {
  // On a phone, focusing the menu's field opens the on-screen keyboard, which
  // resizes the page - closing on resize lost the half-typed word.
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  const span = word(document, 'שרן');
  span.getBoundingClientRect = () => ({ top: 100, bottom: 120, left: 300, right: 340, width: 40, height: 20 });
  open(document, 'שרן');

  span.getBoundingClientRect = () => ({ top: 50, bottom: 70, left: 300, right: 340, width: 40, height: 20 });
  window.dispatchEvent(new window.Event('resize'));

  const menu = document.querySelector('.fix-menu');
  assert.ok(menu, 'still open');
  assert.equal(menu.style.top, '76px', 'moved with the word');

  window.close();
});

test('the menu closes once its word has scrolled off screen', async () => {
  const { window, document } = buildWindow(getFixtureHtml('fixable'));
  const span = word(document, 'שרן');
  open(document, 'שרן');
  await wait(450);

  span.getBoundingClientRect = () => ({ top: -80, bottom: -60, left: 300, right: 340, width: 40, height: 20 });
  window.dispatchEvent(new window.Event('scroll'));

  assert.equal(document.querySelector('.fix-menu'), null);

  window.close();
});
