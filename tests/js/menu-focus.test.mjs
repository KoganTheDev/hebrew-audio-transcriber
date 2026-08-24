// Regression coverage for C4: closeMenu() used to clear aria-expanded but
// never return focus to the trigger, unlike bindHelp()'s openHelp()/
// closeHelp() pair - a keyboard user who opened a .spk-menu or
// .swatch-menu (which auto-focuses its first item on open, see
// toggleMenu()) lost their place entirely once Escape (or picking an item)
// tore the menu down, with focus falling back to <body>. The trigger is a
// bubble's own .bubble-spk now - there is no more cluster-header .spk to
// open a menu from at all (see the review plan's "flat sentence cards"
// section) - so every test here drives that control instead.
//
// The fix reuses that same opener-capture-and-restore shape rather than
// inventing a second one, with one twist closeMenu() needs that the help
// panel doesn't: it also serves as bindMenus()'s catch-all for "the reader
// clicked elsewhere entirely" (see closeMenu()'s own comment), so it must
// NOT steal focus back to the trigger in that case - only when focus was
// actually inside the menu being torn down.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function keydown(el, key) {
  const view = (el.ownerDocument || el).defaultView;
  el.dispatchEvent(new view.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

test('Escape after opening a speaker reassignment menu returns focus to the .bubble-spk trigger', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const trigger = document.querySelector('.bubble[data-line="0-0-0"] .bubble-spk');

  click(trigger);
  const menu = document.querySelector('.spk-menu');
  assert.ok(menu, 'expected the reassignment menu to open');
  assert.equal(document.activeElement, menu.querySelector('[role="menuitemradio"]'), 'the first item should auto-focus on open');

  keydown(document, 'Escape');

  assert.equal(document.querySelector('.spk-menu'), null, 'the menu must close on Escape');
  assert.equal(document.activeElement, trigger, 'focus must return to the .bubble-spk trigger that opened it');

  window.close();
});

test('Escape after opening a swatch colour menu returns focus to the .swatch-trigger', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const trigger = document.querySelector('.swatch-trigger');

  click(trigger);
  assert.ok(document.querySelector('.swatch-menu'));

  keydown(document, 'Escape');

  assert.equal(document.activeElement, trigger);

  window.close();
});

test('picking a reassignment menu item also returns focus to the trigger afterwards', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const trigger = document.querySelector('.bubble[data-line="0-0-0"] .bubble-spk');

  click(trigger);
  click(document.querySelector('.spk-menu-item[data-speaker="1"]'));

  assert.equal(document.querySelector('.spk-menu'), null);
  assert.equal(document.activeElement, trigger, 'the trigger element persists across reassignment and should regain focus');

  window.close();
});

test('a click elsewhere that closes an open menu does not steal focus back to the trigger', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const trigger = document.querySelector('.bubble[data-line="0-0-0"] .bubble-spk');
  const elsewhere = document.getElementById('search');

  click(trigger);
  assert.ok(document.querySelector('.spk-menu'));

  elsewhere.focus();
  click(elsewhere);

  assert.equal(document.querySelector('.spk-menu'), null, 'clicking elsewhere must still close the open menu');
  assert.equal(document.activeElement, elsewhere, 'the reader\'s own click target must keep focus, not be overridden by the trigger restore');

  window.close();
});
