// Behavioural coverage for bindHelp() (transcript.js): open/close, Escape,
// scrim click, and focus restore to whichever element opened the panel -
// see openHelp()/closeHelp()'s own comments for why `opener` is captured
// fresh on every open rather than hardcoded to the toolbar button.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function keydown(el, key) {
  el.dispatchEvent(new el.ownerDocument.defaultView.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

function open(document) {
  const window = document.defaultView;
  const btn = document.getElementById('help');
  btn.focus();
  assert.equal(window.document.activeElement, btn);
  click(btn);
  return { btn, panel: document.getElementById('help-panel') };
}

test('the help button opens the panel, clears hidden, and marks aria-expanded', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { btn, panel } = open(document);

  assert.equal(panel.hidden, false);
  assert.equal(btn.getAttribute('aria-expanded'), 'true');

  window.close();
});

test('the close button hides the panel again and clears aria-expanded', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { btn, panel } = open(document);

  click(document.getElementById('help-close'));

  assert.equal(panel.hidden, true);
  assert.equal(btn.getAttribute('aria-expanded'), 'false');

  window.close();
});

test('Escape closes the panel while it is open', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { panel } = open(document);

  keydown(panel, 'Escape');

  assert.equal(panel.hidden, true);

  window.close();
});

test('clicking the scrim (the panel element itself, not the sheet inside it) closes the panel', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { panel } = open(document);

  click(panel);
  assert.equal(panel.hidden, true, 'a click on the scrim must close the panel');

  window.close();
});

test('clicking inside the sheet does not close the panel', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { panel } = open(document);

  const title = document.getElementById('help-title');
  assert.ok(title, 'expected #help-title inside the sheet');
  click(title);

  assert.equal(panel.hidden, false, 'a click inside the sheet must not bubble into closing it');

  window.close();
});

test('focus returns to the button that opened the panel once it closes', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { btn, panel } = open(document);

  // openHelp() moves focus onto the close button - part of the same
  // contract, checked here so the return-to-opener assertion below is
  // proven against a focus that actually moved, not one that never left.
  assert.equal(document.activeElement, document.getElementById('help-close'));

  keydown(panel, 'Escape');

  assert.equal(document.activeElement, btn, 'focus must return to #help on close');

  window.close();
});

// The full Tab-wrap round trip (last -> first -> last again) is exercised
// in tests/js/tour.test.mjs instead of here: the tour card's own focus trap
// (chrome.card, same trapTabKey()/focusableIn() functions the help panel
// uses) has an all-<button> focusable set with nothing decorative in it,
// where the help panel's own set ends on an SVG <use> icon that jsdom
// cannot actually move focus onto (calling .focus() on a non-tabbable SVG
// element is a no-op in jsdom, matching a real browser's own behaviour for
// an element with no tabindex) - not something this test can drive
// reliably, so the shared mechanism is proven through the cleaner of its
// two callers instead of faked here.

test('#tour-start closes the help panel and hands off to the tour', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const { panel } = open(document);

  click(document.getElementById('tour-start'));

  assert.equal(panel.hidden, true, 'help panel must close when the tour starts');
  assert.ok(document.querySelector('.tour-card'), 'the tour must actually have started');

  window.close();
});
