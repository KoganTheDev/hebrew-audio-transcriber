// Behavioural coverage for a handful of transcript.js mechanisms that used
// to be checked only by grepping transcript.js/transcript.css for exact
// source text (see tests/test_formatting.py's TestPlayPauseGlyph,
// TestPopoverStackingAndAnchoring and TestKeyboardModalityFlag, which used
// to hold the JS half of what is tested here): the play/pause glyph swap,
// the .menu-open stacking class, the swatch menu's detach-to-<body>
// behaviour, and the keyboard-modality flag bindKeyboardModality() sets.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function fire(el, type) {
  el.dispatchEvent(new el.ownerDocument.defaultView.Event(type, { bubbles: true }));
}

function keydown(el, key) {
  const view = (el.ownerDocument || el).defaultView;
  el.dispatchEvent(new view.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

function pointerdown(el) {
  const view = (el.ownerDocument || el).defaultView;
  const Ctor = view.PointerEvent || view.MouseEvent;
  el.dispatchEvent(new Ctor('pointerdown', { bubbles: true }));
}

test('the play/pause glyph and its aria-label swap together off the audio element\'s own play/pause events', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const audio = document.getElementById('audio');
  const toggle = document.getElementById('player-toggle');
  const use = toggle.querySelector('use');

  assert.equal(use.getAttribute('href'), '#i-play');

  // Driven off the audio element's own events, not the toggle's click
  // handler (see syncToggleGlyph()'s own comment) - a programmatic pause,
  // like the range-bound stop in the timeupdate handler, has to update the
  // glyph too, so this fires the audio event directly rather than clicking
  // the button. jsdom does not implement HTMLMediaElement's play()/pause()
  // (audio.paused stays true forever regardless of what actually happened),
  // and syncToggleGlyph() reads audio.paused/audio.ended, not the event
  // itself - so .paused is stubbed here to whatever state the fired event
  // claims, the same way a real browser would have already updated it by
  // the time the event handler runs.
  Object.defineProperty(audio, 'paused', { value: false, configurable: true });
  fire(audio, 'play');
  assert.equal(use.getAttribute('href'), '#i-pause');
  assert.match(toggle.getAttribute('aria-label'), /pause/i);

  Object.defineProperty(audio, 'paused', { value: true, configurable: true });
  fire(audio, 'pause');
  assert.equal(use.getAttribute('href'), '#i-play');
  assert.match(toggle.getAttribute('aria-label'), /play/i);

  window.close();
});

test('opening a turn\'s reassignment menu raises the card with .menu-open, closing it lowers it again', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const turn = document.querySelector('.turn[data-turn="0-0"]');

  assert.equal(turn.classList.contains('menu-open'), false);

  click(turn.querySelector('.spk'));
  assert.ok(document.querySelector('.spk-menu'), 'expected the reassignment menu to open');
  assert.equal(turn.classList.contains('menu-open'), true);

  keydown(document, 'Escape');
  assert.equal(turn.classList.contains('menu-open'), false);

  window.close();
});

test('the swatch colour menu detaches to <body> as a fixed-position popover, not a child of the scrolling sidebar', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const trigger = document.querySelector('.swatch-trigger');
  const outline = document.getElementById('outline');

  click(trigger);
  const menu = document.querySelector('.swatch-menu');
  assert.ok(menu, 'expected the swatch menu to open');
  assert.equal(menu.parentElement, document.body, 'the menu must be appended to <body>, not left inside .outline');
  assert.equal(outline.contains(menu), false);
  assert.equal(menu.style.position, 'fixed');

  window.close();
});

test('Tab sets data-kbd on <html>, marking keyboard modality', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  assert.equal(document.documentElement.hasAttribute('data-kbd'), false);
  keydown(document, 'Tab');
  assert.equal(document.documentElement.getAttribute('data-kbd'), 'true');

  window.close();
});

test('a pointerdown clears the keyboard-modality flag again', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  keydown(document, 'Tab');
  assert.equal(document.documentElement.getAttribute('data-kbd'), 'true');

  pointerdown(document);
  assert.equal(document.documentElement.hasAttribute('data-kbd'), false);

  window.close();
});
