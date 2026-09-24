// Behavioural coverage for saveDocument()/saveCopyAs() (core/assets/js/56-export.js)
// and the #export/Ctrl+S/Ctrl+Shift+S wiring in 72-chrome.js.
//
// jsdom implements neither the File System Access API nor IndexedDB, so both
// are stubbed per test rather than globally in harness.mjs - most tests in
// this suite never touch either. window.showSaveFilePicker is left entirely
// undefined for the "no File System Access" tests, which is exactly the
// shape a real Firefox window has today.
//
// IndexedDB is deliberately NOT stubbed anywhere here: 56-export.js already
// wraps every indexedDB call in a Promise and swallows its own rejection
// (see storeHandle()'s and ensureFileHandle()'s comments), so a missing
// indexedDB behaves the same as a browser that has one but fails to persist
// the handle across a reload - it just means Save always falls through to
// the picker instead of silently reusing a stored handle. What CAN be
// tested without it is exactly what the task calls for: a handle bound
// in-memory this session is reused without reopening the picker.

import test from 'node:test';
import assert from 'node:assert/strict';
import { getFixtureHtml, buildWindow } from './harness.mjs';

function click(el) {
  el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function ctrlS(document, { shift = false } = {}) {
  const window = document.defaultView;
  document.dispatchEvent(new window.KeyboardEvent('keydown', {
    key: 'S', ctrlKey: true, shiftKey: shift, bubbles: true, cancelable: true,
  }));
}

function typeInto(body, text) {
  body.textContent = '';
  const p = body.ownerDocument.createElement('p');
  p.textContent = text;
  body.appendChild(p);
  body.dispatchEvent(new body.ownerDocument.defaultView.Event('input', { bubbles: true }));
}

// Real setTimeout, same as every other autosave-adjacent test in this
// suite - saveDocument()/save() both run their work off a promise chain and
// a 400ms debounce respectively.
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stubHandle(writes) {
  return {
    createWritable() {
      return Promise.resolve({
        write(html) { writes.push(html); return Promise.resolve(); },
        close() { return Promise.resolve(); },
      });
    },
  };
}

test('Save opens the native picker and writes the serialised document when File System Access is available', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const writes = [];
  let pickCount = 0;
  window.showSaveFilePicker = () => { pickCount++; return Promise.resolve(stubHandle(writes)); };

  click(document.getElementById('export'));
  await wait(50);

  assert.equal(pickCount, 1);
  assert.equal(writes.length, 1);
  assert.ok(writes[0].startsWith('<!doctype html>'));
  assert.equal(document.getElementById('status').dataset.kind, 'saved');

  window.close();
});

test('Save falls back to the anchor-download Blob when File System Access is unavailable', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  assert.equal(typeof window.showSaveFilePicker, 'undefined', 'this test is only meaningful without the API');

  // jsdom implements neither half of the Blob URL API - see bubbles.test.mjs.
  window.URL.createObjectURL = () => 'blob:stub';
  window.URL.revokeObjectURL = () => {};

  click(document.getElementById('export'));
  await wait(50);

  assert.equal(document.getElementById('status').dataset.kind, 'saved');

  window.close();
});

test('cancelling the save picker leaves the document dirty and binds no handle', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const statusEl = document.getElementById('status');
  statusEl.dataset.kind = 'local'; // an edit already sitting unsaved, as if typed a moment ago

  const abort = new Error('cancelled');
  abort.name = 'AbortError';
  let pickCount = 0;
  window.showSaveFilePicker = () => { pickCount++; return Promise.reject(abort); };

  click(document.getElementById('export'));
  await wait(50);

  assert.equal(statusEl.dataset.kind, 'local', 'a cancelled picker must not flip the pill to saved');

  // No handle can have been bound by a cancelled pick: a later, successful
  // Save has to open the picker again rather than silently reusing one.
  const writes = [];
  window.showSaveFilePicker = () => { pickCount++; return Promise.resolve(stubHandle(writes)); };
  click(document.getElementById('export'));
  await wait(50);

  assert.equal(pickCount, 2, 'a fresh Save after a cancel must open the picker again');
  assert.equal(writes.length, 1);
  assert.equal(statusEl.dataset.kind, 'saved');

  window.close();
});

test('a handle bound by Save is reused on the next Save without reopening the picker', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const writes = [];
  let pickCount = 0;
  window.showSaveFilePicker = () => { pickCount++; return Promise.resolve(stubHandle(writes)); };

  click(document.getElementById('export'));
  await wait(50);
  assert.equal(pickCount, 1);
  assert.equal(writes.length, 1);

  click(document.getElementById('export'));
  await wait(50);
  assert.equal(pickCount, 1, 'the second Save must not reopen the picker');
  assert.equal(writes.length, 2, 'but it must still write the fresh document to the same handle');

  window.close();
});

test('Ctrl+Shift+S ("Save a copy") opens its own picker and does not rebind the handle Save uses', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const writesA = [];
  const writesB = [];
  const handles = [stubHandle(writesA), stubHandle(writesB)];
  let pickCount = 0;
  window.showSaveFilePicker = () => { const h = handles[pickCount]; pickCount++; return Promise.resolve(h); };

  // Save binds handle A.
  click(document.getElementById('export'));
  await wait(50);
  assert.equal(pickCount, 1);
  assert.equal(writesA.length, 1);

  // Save a copy elsewhere: a second picker, handle B, but Save's own binding
  // is untouched.
  ctrlS(document, { shift: true });
  await wait(50);
  assert.equal(pickCount, 2, 'Ctrl+Shift+S must open its own picker');
  assert.equal(writesB.length, 1);

  // A further Save still lands on A, not B - the copy never rebound it.
  click(document.getElementById('export'));
  await wait(50);
  assert.equal(pickCount, 2, 'Save must still reuse the handle it already had');
  assert.equal(writesA.length, 2);
  assert.equal(writesB.length, 1);

  window.close();
});

test('a failing disk write does not lose the edit - it falls back to localStorage and flags the error', async () => {
  const { window, document } = buildWindow(getFixtureHtml('full'));
  const key = `hebrew-transcript:${document.documentElement.dataset.docId}`;
  const turn = document.querySelector('.turn[data-turn="0-0"]');
  const body = turn.querySelector('.body');

  typeInto(body, 'a corrected line');

  const failingHandle = { createWritable() { return Promise.reject(new Error('disk full')); } };
  window.showSaveFilePicker = () => Promise.resolve(failingHandle);

  click(document.getElementById('export'));
  await wait(50);
  // The failure is surfaced right away...
  assert.equal(document.getElementById('status').dataset.kind, 'error');

  // ...and save()'s own localStorage write (08-storage.js), re-triggered by
  // the failure, lands behind its usual 400ms debounce - by then the pill
  // reads "local", the same as any other localStorage-only save, because
  // the edit really is safe again, just not on disk.
  await wait(500);
  assert.equal(document.getElementById('status').dataset.kind, 'local');
  const stored = JSON.parse(window.localStorage.getItem(key));
  assert.ok(stored && Object.keys(stored.turns).length > 0,
    'the edit must still be present in localStorage after the disk write failed');

  window.close();
});
