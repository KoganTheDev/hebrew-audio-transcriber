// Regression coverage for a reported bug: after recolouring a speaker and
// reopening the file, the sidebar dot showed the chosen colour while that
// speaker's cards showed the original one.
//
// Cause: recolourSpeaker() repainted the roster row, the turns AND the
// bubbles, but persisted only the row's palette, and applySpeakerState()
// restored only the row. Every card still carried the server-rendered
// data-palette (speaker % 8, _palette_index() in formatting/chrome.py), so a
// reload left two sources of truth for one speaker's colour.
//
// These drive the real save/reload round trip rather than asserting on
// internals, so the fix is graded on the thing the user actually saw.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Opens speaker 0's colour menu and picks a palette slot it does not already
// use, so "did anything change" is unambiguous.
function recolour(doc, speakerId, palette) {
  const row = doc.querySelector(`.speaker-row[data-speaker="${speakerId}"]`);
  click(row.querySelector('.swatch-trigger'));
  const item = doc.querySelector(`.swatch-menu .swatch-menu-item[data-palette="${palette}"]`);
  assert.ok(item, `expected a swatch for palette ${palette}`);
  click(item);
}

// Scoped to ONE file's section on purpose. Speaker identities are per-file
// (see _render_speakers_html()'s docstring: speaker 1 in one recording is
// rarely the same person as speaker 1 in another), and the "full" fixture has
// two files that each have a speaker 0. A document-wide query would sweep up
// the other file's speaker 0, which a recolour here must NOT touch.
function palettesFor(doc, fileIndex, speakerId) {
  const strip = doc.querySelector(`.speakers[data-file="${fileIndex}"]`);
  const section = doc.querySelector(`.source[data-file="${fileIndex}"]`);
  return {
    row: strip.querySelector(`.speaker-row[data-speaker="${speakerId}"]`).dataset.palette,
    turns: [...section.querySelectorAll(`.turn[data-speaker="${speakerId}"]`)].map((t) => t.dataset.palette),
    bubbles: [...section.querySelectorAll(`.bubble[data-speaker="${speakerId}"]`)].map((b) => b.dataset.palette),
    chips: [...section.querySelectorAll(`.bubble-spk[data-speaker="${speakerId}"]`)].map((c) => c.dataset.palette),
  };
}

test('recolouring repaints the roster dot and every card together', () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));

  recolour(document, 0, 5);

  const seen = palettesFor(document, 0, 0);
  assert.equal(seen.row, '5');
  assert.ok(seen.turns.length > 0 && seen.bubbles.length > 0, 'fixture must have cards to repaint');
  seen.turns.forEach((p) => assert.equal(p, '5'));
  seen.bubbles.forEach((p) => assert.equal(p, '5'));
  seen.chips.forEach((p) => assert.equal(p, '5'));

  window.close();
});

test('the recolour survives a reload on the CARDS, not just on the sidebar dot', async () => {
  const seedKey = 'hebrew-transcript:js-fixture-full';
  const first = buildWindow(getFixtureHtml('full'));

  recolour(first.document, 0, 5);
  await wait(600);
  const saved = first.window.localStorage.getItem(seedKey);
  assert.ok(saved, 'the recolour has to be persisted');
  assert.equal(JSON.parse(saved).speakers['0']['0'].palette, 5);
  first.window.close();

  const second = buildWindow(getFixtureHtml('full'), { [seedKey]: saved });
  const seen = palettesFor(second.document, 0, 0);

  assert.equal(seen.row, '5', 'the sidebar dot restored correctly even before the fix');
  // This is the bug. The cards came back carrying the server-rendered
  // speaker % 8 - palette "0" for speaker 0 - while the dot showed 5.
  assert.ok(seen.turns.length > 0, 'fixture must have turns for this speaker');
  seen.turns.forEach((p) => assert.equal(p, '5', 'a turn must reload in the chosen colour'));
  seen.bubbles.forEach((p) => assert.equal(p, '5', 'a bubble must reload in the chosen colour'));
  seen.chips.forEach((p) => assert.equal(p, '5', 'a chip must reload in the chosen colour'));

  second.window.close();
});

test('a reassignment to a speaker with no roster row still gets a real palette slot', async () => {
  // Only eight [data-palette="N"] rules exist (00-tokens.css). The fallback
  // used a raw speaker id, so an id of 8 or more matched no rule at all and
  // --spk never resolved - the chip fell back to currentColor.
  const seedKey = 'hebrew-transcript:js-fixture-full';
  const seed = JSON.stringify({
    turns: {}, names: {}, flags: false, theme: null, opts: {},
    speakers: {}, assign: { '0-0': 9 }, assignLine: {},
  });

  const { window, document } = buildWindow(getFixtureHtml('full'), { [seedKey]: seed });

  const turn = document.querySelector('.turn[data-turn="0-0"]');
  assert.equal(turn.dataset.speaker, '9');
  const palette = Number(turn.dataset.palette);
  assert.ok(palette >= 0 && palette <= 7,
    `palette must be one of the eight slots, got ${turn.dataset.palette}`);
  assert.equal(palette, 1, '9 % 8 - the same rule the server uses');

  window.close();
});
