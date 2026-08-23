  // ---------------------------------------------------------------- storage

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { state = Object.assign(state, JSON.parse(raw)); }
    } catch (e) {
      // Storage disabled, quota exhausted, or a corrupt entry. Losing restored
      // edits is bad; a document that refuses to open is worse.
      console.warn('could not read saved edits', e);
    }
  }

  function hasLocalChanges() {
    return Object.keys(state.turns).length > 0 || Object.keys(state.names).length > 0
      || Object.keys(state.speakers).length > 0 || Object.keys(state.assign).length > 0
      || Object.keys(state.assignLine).length > 0;
  }

  function save() {
    setStatus('saving');
    clearTimeout(saveTimer);
    // Debounced so a fast typist writes once per pause, not once per keystroke.
    saveTimer = setTimeout(function () {
      try {
        localStorage.setItem(KEY, JSON.stringify(state));
        exported = false;
        setStatus('local');
      } catch (e) {
        setStatus('error');
      }
    }, 400);
  }

  function setStatus(kind) {
    if (!statusEl) { return; }
    // "local" is the honest state and the one the reader is usually in: the
    // edit is safely in this browser, but the .html on disk does not contain
    // it and will not until "Save a copy" is used. Reporting a plain "Saved"
    // there would imply the file had been updated, which is exactly the thing
    // a file:// page cannot do.
    statusEl.textContent = {
      saving: t('status_saving', 'Saving…'),
      saved: t('status_saved', 'Saved'),
      local: t('status_local', 'Saved in browser'),
      error: t('status_error', 'Could not save')
    }[kind];
    statusEl.dataset.kind = kind;
  }
