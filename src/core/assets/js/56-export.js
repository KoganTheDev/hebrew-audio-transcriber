
  // The bound file for this session, once Save has picked or reused one.
  // null until then, which is also what tells saveDocument() and
  // scheduleDiskAutosave() there is nothing to write to yet - see the
  // module comment below for why this cannot be restored from IndexedDB
  // automatically on load.
  var fileHandle = null;
  var diskAutosaveTimer = null;

  function supportsFileSystemAccess() {
    return typeof window.showSaveFilePicker === 'function';
  }

  // A FileSystemFileHandle is a live object with methods
  // (queryPermission/createWritable/...), and localStorage can only hold
  // strings - JSON.stringify(handle) would throw away everything that makes
  // it useful. IndexedDB's structured-clone algorithm knows how to store and
  // restore a handle intact, which is the only way "the same file, next
  // Save" can survive a reload. Keyed by DOC_ID (00-preamble.js) the same
  // way the localStorage entry is, so each document remembers its own file.
  var HANDLE_DB_NAME = 'hebrew-transcript-handles';
  var HANDLE_STORE = 'handles';

  function openHandleDb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(HANDLE_DB_NAME, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(HANDLE_STORE); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function loadStoredHandle() {
    return openHandleDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var req = db.transaction(HANDLE_STORE, 'readonly').objectStore(HANDLE_STORE).get(DOC_ID);
        req.onsuccess = function () { resolve(req.result || null); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function storeHandle(handle) {
    return openHandleDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(HANDLE_STORE, 'readwrite');
        tx.objectStore(HANDLE_STORE).put(handle, DOC_ID);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  // Permission never survives a reload - queryPermission comes back
  // "prompt" every time even for a handle IndexedDB just handed back intact
  // (verified against real Chrome on a file:// document) - so a stored
  // handle always needs one requestPermission call before it can be written
  // to again. requestPermission needs a live user gesture, which is exactly
  // what a click handler (or a keydown handler for Ctrl+S) is; do not call
  // it from anywhere else.
  function requestReadWrite(handle) {
    return handle.queryPermission({ mode: 'readwrite' }).then(function (status) {
      if (status === 'granted') { return true; }
      return handle.requestPermission({ mode: 'readwrite' }).then(function (status2) {
        return status2 === 'granted';
      });
    });
  }

  // `id` groups this picker with itself across calls so Chrome reopens it in
  // the last folder used for a transcript rather than wherever the OS
  // defaults to - this rests on the File System Access spec's own
  // description of startIn/id, not on anything observed here (the picker
  // itself cannot be exercised in this environment - see the module's own
  // manual-check entry). Harmless if a browser ignores it.
  function openSavePicker() {
    return window.showSaveFilePicker({
      suggestedName: (DATA.filename || 'transcript') + ' (edited).html',
      id: 'transcript',
      types: [{ description: 'HTML document', accept: { 'text/html': ['.html'] } }],
    });
  }

  // A handle fresh out of the picker already carries write permission - the
  // gesture that opened the picker grants it - so only a handle retrieved
  // from IndexedDB (ensureFileHandle's other branch) ever needs
  // requestReadWrite.
  function pickAndBindHandle() {
    return openSavePicker().then(function (handle) {
      fileHandle = handle;
      // Best-effort: losing the stored handle only means the next Save (in
      // some future session) opens the picker again, not that this one fails.
      return storeHandle(handle).catch(function () {}).then(function () { return handle; });
    });
  }

  // The handle Save should write to: the one already bound this session, or
  // the one IndexedDB remembers from a previous session (after one
  // permission prompt), or - if neither exists or that permission is
  // refused - a fresh one from the picker.
  function ensureFileHandle() {
    if (fileHandle) { return Promise.resolve(fileHandle); }
    return loadStoredHandle().catch(function () { return null; }).then(function (stored) {
      if (!stored) { return pickAndBindHandle(); }
      return requestReadWrite(stored).then(function (granted) {
        if (granted) { fileHandle = stored; return stored; }
        return pickAndBindHandle();
      });
    });
  }

  function writeToHandle(handle, html) {
    return handle.createWritable().then(function (writable) {
      return writable.write(html).then(function () { return writable.close(); });
    });
  }

  // A permission revoke, a deleted file, a full disk - whatever the cause,
  // the edit already sitting in `state` must not disappear just because the
  // disk write did. save() (08-storage.js) is called directly rather than
  // waited on, since the edit is already flowing into localStorage on its
  // own debounce and this only needs to make sure that has actually
  // happened; saveFailedWarned (08-storage.js) keeps the toast one-shot
  // instead of re-showing it on every failed autosave tick.
  //
  // `fileHandle` is unbound here on purpose: leaving a handle that just
  // failed to write bound would make every future keystroke's save()
  // re-arm scheduleDiskAutosave(), which would fail again 400ms later and
  // call back in here - and each of those calls its own clearTimeout on
  // save()'s timer would perpetually cancel the very localStorage write
  // this function exists to guarantee, never letting it actually land.
  // Unbinding stops the retry loop; the next explicit Save opens the
  // picker again, which is the right moment to ask the reader for a
  // working destination.
  function onSaveFailure() {
    fileHandle = null;
    clearTimeout(diskAutosaveTimer);
    save();
    setStatus('error');
    if (!saveFailedWarned) {
      saveFailedWarned = true;
      showToast(t('save_failed',
        'Could not save in the browser - use "Save a copy" to keep your edits.'));
    }
  }

  // Runs once Save has bound `fileHandle` for this session - permission is
  // already granted at that point, so this needs no further prompt until
  // the next reload. Its own debounce timer, not chained off save()'s: both
  // fire off the same edit and run in parallel, at the same 400ms cadence,
  // rather than the disk write waiting on the localStorage write to finish
  // first.
  function scheduleDiskAutosave() {
    if (!fileHandle) { return; }
    clearTimeout(diskAutosaveTimer);
    diskAutosaveTimer = setTimeout(function () {
      writeToHandle(fileHandle, serializeDocument()).then(function () {
        exported = true;
        setStatus('saved');
      }).catch(onSaveFailure);
    }, 400);
  }

  // The document, ready to leave the page: search cleared, uncertain-word
  // shading stripped, every pending keystroke-deferred rebuild flushed, and
  // transient view state (a half-typed query, an audio path only meaningful
  // on this machine) reset so the copy opens at rest. Shared by every path
  // that writes the document out - the Blob download, Save, and Save a copy
  // all serialise it exactly the same way.
  function serializeDocument() {
    clearSearch();
    var wasFlagged = state.flags;
    if (wasFlagged) { setFlags(false); }

    // Serialising reads attributes, but typing only updates properties, so
    // form state has to be written back before it can survive the export.
    // Any keystroke-deferred panel rebuild has to land before the DOM is
    // serialised, or the exported copy carries a stale plain-text panel.
    flushPlain();
    bakeFormState();

    // Strip transient view state - a half-typed query, an audio path that only
    // meant something on this machine - so the copy opens at rest, not frozen
    // mid-session.
    var restore = resetTransientState();

    // The live DOM already holds the edits and names, so serialising it is the
    // export: the copy is a working editor with the same doc id.
    var html = '<!doctype html>\n' + document.documentElement.outerHTML;
    restore();

    if (wasFlagged) { setFlags(true); }
    return html;
  }

  // The fallback path for a browser with no File System Access API - Firefox
  // as of this writing, and the only path #export/Ctrl+S ever had before it.
  // Also what a File System Access browser falls back to nowhere: once that
  // API exists, saveDocument()/saveCopyAs() below take over #export/Ctrl+S
  // and Ctrl+Shift+S respectively, and this only remains their own fallback
  // branch.
  function exportCopy() {
    var html = serializeDocument();
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (DATA.filename || 'transcript') + ' (edited).html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    exported = true;
    setStatus('saved');
  }

  // #export's click handler, and Ctrl+S's, in a File System Access browser:
  // writes to the document's own bound file, picking one first if none is
  // bound yet. Falls back to exportCopy() where the API does not exist at
  // all.
  function saveDocument() {
    if (!supportsFileSystemAccess()) { exportCopy(); return; }
    ensureFileHandle().then(function (handle) {
      return writeToHandle(handle, serializeDocument());
    }).then(function () {
      exported = true;
      setStatus('saved');
    }).catch(function (err) {
      // The user closing the picker without choosing anything - leave the
      // document exactly as dirty as it already was, with no handle bound,
      // rather than treating a deliberate cancel as a failure.
      if (err && err.name === 'AbortError') { return; }
      onSaveFailure();
    });
  }

  // Ctrl+Shift+S only - always opens the picker and writes there, without
  // touching `fileHandle`, so Save keeps writing wherever it already was.
  function saveCopyAs() {
    if (!supportsFileSystemAccess()) { exportCopy(); return; }
    openSavePicker().then(function (handle) {
      return writeToHandle(handle, serializeDocument());
    }).catch(function (err) {
      if (err && err.name === 'AbortError') { return; }
      onSaveFailure();
    });
  }

  function bakeFormState() {
    // Without this the copy carries speaker names in the turn labels but an
    // empty name box, and on a machine with no saved state the first edit
    // would read that empty box and reset the name to its fallback.
    document.querySelectorAll('.speaker-name').forEach(function (input) {
      input.setAttribute('value', input.value);
    });
    // Per-bubble speaker overrides (state.assignLine, js/24-speakers-menus.js)
    // need no baking: paintBubbleOverride() writes them as attributes and text
    // nodes, which outerHTML already carries verbatim.
    document.querySelectorAll('.plain input[type="checkbox"]').forEach(function (box) {
      if (box.checked) {
        box.setAttribute('checked', '');
      } else {
        box.removeAttribute('checked');
      }
    });
  }

  function resetTransientState() {
    var searchInput = document.getElementById('search');
    var player = document.getElementById('player');
    var audio = document.getElementById('audio');
    var count = document.getElementById('search-count');

    var previous = {
      query: searchInput ? searchInput.value : '',
      audioSrc: audio ? audio.getAttribute('src') : null,
      playerHidden: player ? player.hidden : true
    };

    if (searchInput) { searchInput.value = ''; }
    if (count) { count.textContent = ''; }
    if (player) { player.hidden = true; }
    // Remove the attribute rather than blanking it: src="" resolves to the
    // document URL, which makes the browser try to play the HTML itself.
    if (audio) { audio.removeAttribute('src'); }

    return function () {
      if (searchInput) { searchInput.value = previous.query; }
      if (player) { player.hidden = previous.playerHidden; }
      if (audio && previous.audioSrc) { audio.setAttribute('src', previous.audioSrc); }
    };
  }
