// Behavioural coverage for removing a speaker from the roster.
//
// The destructive counterpart to addSpeaker(). Three things make it more than
// a row.remove():
//
//   - applySpeakerState() (js/24-speakers-menus.js) only ever CREATES rows, so
//     a server-rendered row comes back on every reload. Deleting one has to
//     persist a tombstone, or the delete silently undoes itself.
//   - addSpeaker() derived the new palette and name from the ROW COUNT while
//     ids come from maxId + 1. Those agree only while ids are contiguous, and
//     deleting a middle speaker is exactly what breaks that - the next add
//     would collide with a surviving row.
//   - The cards belonging to the deleted speaker have to land somewhere. They
//     become unattributed (the same resting state a turn diarization could not
//     place uses), which keeps them visible and reassignable rather than
//     silently inheriting a neighbour's identity.
//
// Fixture ("three-speakers"): one file, speakers 0, 1 and 2, with speaker 1
// holding TWO turns ("0-1" and "0-3").

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// The delete asks for confirmation - the one destructive action in this
// document. Tests drive it by answering that prompt.
function withConfirm(win, answer) {
  win.confirm = () => answer;
}

function removeSpeaker(win, doc, id) {
  withConfirm(win, true);
  const row = doc.querySelector(`.speaker-row[data-speaker="${id}"]`);
  click(row.querySelector('.remove-speaker'));
}

test('the remove control is hidden at two speakers and shown at three', () => {
  const two = buildWindow(getFixtureHtml('full'));
  const twoRows = two.document.querySelectorAll('.speakers[data-file="0"] .speaker-row');
  assert.equal(twoRows.length, 2);
  twoRows.forEach((row) => {
    assert.equal(row.querySelector('.remove-speaker').hidden, true,
      'two speakers is the floor - a one-speaker roster cannot express a conversation');
  });
  two.window.close();

  const three = buildWindow(getFixtureHtml('three-speakers'));
  three.document.querySelectorAll('.speaker-row').forEach((row) => {
    assert.equal(row.querySelector('.remove-speaker').hidden, false);
  });
  three.window.close();
});

test('removing a speaker drops the row and unattributes every card that carried it', () => {
  const { window, document } = buildWindow(getFixtureHtml('three-speakers'));

  removeSpeaker(window, document, 1);

  assert.equal(document.querySelector('.speaker-row[data-speaker="1"]'), null);
  assert.equal(document.querySelectorAll('.speaker-row').length, 2);

  // Speaker 1 held two separate turns - both must be dealt with, not just the
  // first one found.
  assert.equal(document.querySelectorAll('.turn[data-speaker="1"]').length, 0);
  assert.equal(document.querySelectorAll('.bubble[data-speaker="1"]').length, 0);

  const orphaned = document.querySelectorAll('.bubble[data-unattributed]');
  assert.equal(orphaned.length, 2, 'both of speaker 1\'s sentences become unattributed');
  orphaned.forEach((bubble) => {
    const chip = bubble.querySelector('.bubble-spk');
    assert.ok(chip, 'the card keeps a chip, which is the only way to reassign it by hand');
    assert.equal(chip.hasAttribute('data-speaker'), false);
    assert.notEqual(chip.querySelector('.bubble-spk-label').textContent.trim(), '');
  });

  // The surviving speakers are untouched.
  assert.ok(document.querySelector('.speaker-row[data-speaker="0"]'));
  assert.ok(document.querySelector('.speaker-row[data-speaker="2"]'));
  assert.equal(document.querySelectorAll('.bubble[data-speaker="2"]').length, 1);

  window.close();
});

test('the removal survives a reload rather than the server-rendered row coming back', async () => {
  const seedKey = 'hebrew-transcript:js-fixture-three';
  const first = buildWindow(getFixtureHtml('three-speakers'));

  removeSpeaker(first.window, first.document, 1);
  await wait(600);
  const saved = first.window.localStorage.getItem(seedKey);
  assert.ok(saved, 'the removal has to be persisted');
  first.window.close();

  const second = buildWindow(getFixtureHtml('three-speakers'), { [seedKey]: saved });
  assert.equal(second.document.querySelector('.speaker-row[data-speaker="1"]'), null,
    'applySpeakerState() only creates rows, so this needs a tombstone to replay');
  assert.equal(second.document.querySelectorAll('.speaker-row').length, 2);
  assert.equal(second.document.querySelectorAll('.bubble[data-unattributed]').length, 2,
    'and the cards it orphaned must come back unattributed too');
  second.window.close();
});

test('adding a speaker after removing a middle one does not collide with a survivor', () => {
  const { window, document } = buildWindow(getFixtureHtml('three-speakers'));

  // Remove the MIDDLE id, leaving 0 and 2 - a non-contiguous roster.
  removeSpeaker(window, document, 1);
  click(document.querySelector('.speakers[data-file="0"] .add-speaker'));

  const rows = [...document.querySelectorAll('.speaker-row')];
  const ids = rows.map((r) => r.dataset.speaker);
  const palettes = rows.map((r) => r.dataset.palette);
  const names = rows.map((r) => r.querySelector('.speaker-name').placeholder);

  assert.equal(new Set(ids).size, ids.length, 'ids must stay unique');
  // The bug this pins: palette and name were derived from the row COUNT. With
  // 0 and 2 surviving, count is 2, so the new speaker would have taken
  // palette 2 and "Speaker 3" - both already owned by the surviving id 2.
  assert.equal(new Set(palettes).size, palettes.length, 'two speakers must never share a colour');
  assert.equal(new Set(names).size, names.length, 'nor a default name');

  window.close();
});

test('assignments pointing at a removed speaker are dropped, not replayed onto a missing row', async () => {
  const seedKey = 'hebrew-transcript:js-fixture-three';
  const { window, document } = buildWindow(getFixtureHtml('three-speakers'));

  // Move one of speaker 0's sentences onto speaker 1, then delete speaker 1.
  const bubble = document.querySelector('.bubble[data-line="0-0-0"]');
  click(bubble.querySelector('.bubble-spk'));
  click(document.querySelector('.spk-menu .spk-menu-item[data-speaker="1"]'));
  assert.equal(document.querySelector('.bubble[data-line="0-0-0"] .bubble-spk').dataset.speaker, '1');

  removeSpeaker(window, document, 1);
  await wait(600);

  const saved = JSON.parse(window.localStorage.getItem(seedKey));
  assert.equal(saved.assignLine['0-0-0'], undefined,
    'a stale assignment would be replayed against a row that no longer exists, '
      + 'which falls back to a raw id for the palette and an empty name - a blank chip');
  assert.equal(
    document.querySelector('.bubble[data-line="0-0-0"]').hasAttribute('data-unattributed'),
    true,
  );

  window.close();
});
