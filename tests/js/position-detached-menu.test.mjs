// Regression coverage for C1: positionDetachedMenu()'s horizontal clamp
// used to always write menu.style.left and blank menu.style.right, which
// undid the RTL branch a few lines above it for any popover wide enough to
// trip the clamp - the swatch-menu's own 8-swatch grid is exactly that
// wide. transcript.js is loaded via the ACTUAL popover path (clicking a
// .swatch-trigger, exercising toggleMenu()/positionDetachedMenu() exactly
// as a reader would) rather than by calling the function directly - it is
// not exported from the module's IIFE, and reaching it through the real
// trigger is also the only way to prove the fix holds along the code path
// that actually ships.
//
// getBoundingClientRect() is jsdom's all-zero stub by default (see
// harness.mjs's own docstring) - both the trigger button's and the menu's
// own rect are patched here to the specific numbers this test is about:
// a trigger near the RTL inline-start edge (the right side of the screen)
// with a popover wide enough to overflow the opposite edge once anchored
// to it, which is exactly the shape that used to trip the buggy clamp.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function withRoutedRect(window, router, fn) {
  const proto = window.Element.prototype;
  const original = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () {
    const routed = router(this);
    return routed || original.call(this);
  };
  try {
    return fn();
  } finally {
    proto.getBoundingClientRect = original;
  }
}

function rect(box) {
  return {
    top: box.top, left: box.left, right: box.right, bottom: box.bottom,
    width: box.width, height: box.height, x: box.left, y: box.top,
    toJSON() { return this; },
  };
}

test('clamping an RTL-anchored popover keeps it on style.right, never switching to style.left', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  Object.defineProperty(document.documentElement, 'clientWidth', { value: 1024, configurable: true });
  document.documentElement.setAttribute('dir', 'rtl');

  const btn = document.querySelector('.swatch-trigger');
  assert.ok(btn, 'expected at least one speaker row with a swatch trigger');

  withRoutedRect(window, (el) => {
    if (el === btn) {
      return rect({ top: 100, left: 900, right: 950, bottom: 130, width: 50, height: 30 });
    }
    if (el.classList && el.classList.contains('swatch-menu')) {
      // Anchored via style.right against a button at x=900..950; an
      // 8-swatch grid this wide overflows the left edge once placed there,
      // which is the exact shape that tripped the pre-fix clamp.
      return rect({ top: 134, left: -40, right: 300, bottom: 400, width: 340, height: 266 });
    }
    return null;
  }, () => {
    click(btn);
  });

  const menu = document.querySelector('.swatch-menu');
  assert.ok(menu, 'expected the swatch menu to have opened');
  assert.equal(menu.style.left, '', 'the RTL clamp must not write style.left at all');
  assert.notEqual(menu.style.right, '', 'the RTL clamp must keep the popover anchored via style.right');

  window.close();
});

test('clamping an RTL-anchored popover overflowing the right edge stays pinned via style.right', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  Object.defineProperty(document.documentElement, 'clientWidth', { value: 1024, configurable: true });
  document.documentElement.setAttribute('dir', 'rtl');

  const btn = document.querySelector('.swatch-trigger');

  withRoutedRect(window, (el) => {
    if (el === btn) {
      return rect({ top: 100, left: 10, right: 60, bottom: 130, width: 50, height: 30 });
    }
    if (el.classList && el.classList.contains('swatch-menu')) {
      // Placed near the left edge (a small style.right computed from the
      // trigger above); wide enough to overflow the RIGHT edge instead.
      return rect({ top: 134, left: 700, right: 1080, bottom: 400, width: 380, height: 266 });
    }
    return null;
  }, () => {
    click(btn);
  });

  const menu = document.querySelector('.swatch-menu');
  assert.equal(menu.style.left, '', 'the RTL clamp must not write style.left at all');
  assert.notEqual(menu.style.right, '');

  window.close();
});

test('clamping an LTR-anchored popover still uses style.left, as before the fix', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  Object.defineProperty(document.documentElement, 'clientWidth', { value: 1024, configurable: true });
  document.documentElement.setAttribute('dir', 'ltr');

  const btn = document.querySelector('.swatch-trigger');

  withRoutedRect(window, (el) => {
    if (el === btn) {
      return rect({ top: 100, left: 10, right: 60, bottom: 130, width: 50, height: 30 });
    }
    if (el.classList && el.classList.contains('swatch-menu')) {
      return rect({ top: 134, left: -40, right: 300, bottom: 400, width: 340, height: 266 });
    }
    return null;
  }, () => {
    click(btn);
  });

  const menu = document.querySelector('.swatch-menu');
  assert.equal(menu.style.left, '8px');
  assert.equal(menu.style.right, '');

  window.close();
});
