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

  // Sets the attribute and nothing else. All four labels are already in the
  // DOM (the renderer emits them) and the stylesheet shows exactly the one
  // this attribute names - which is what keeps the box a fixed width instead
  // of resizing to its text and shoving the whole button row sideways. Do not
  // "simplify" this back into a textContent write: the four stacked labels are
  // the width reserve, so a single label written here would take it away.
  //
  // On the states themselves: "local" is the honest one and the one the reader
  // is usually in - the edit is safely in this browser, but the .html on disk
  // does not contain it and will not until "Save a copy" is used. Reporting a
  // plain "Saved" there would imply the file had been updated, which is
  // exactly the thing a file:// page cannot do.
  function setStatus(kind) {
    if (!statusEl) { return; }
    statusEl.dataset.kind = kind;
  }
