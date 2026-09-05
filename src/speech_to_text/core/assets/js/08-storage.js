
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

  // The renderer emits all four status labels and the stylesheet shows the
  // one this attribute names, which is what keeps the box a fixed width
  // instead of resizing to its text and shoving the button row sideways. Do
  // not "simplify" this into a textContent write: the stacked labels are the
  // width reserve.
  //
  // "local" is the usual state - the edit is in this browser, but the .html
  // on disk does not contain it until "Save a copy" is used. A plain "Saved"
  // would imply the file itself had been updated, which a file:// page cannot
  // do.
  function setStatus(kind) {
    if (!statusEl) { return; }
    statusEl.dataset.kind = kind;
  }
