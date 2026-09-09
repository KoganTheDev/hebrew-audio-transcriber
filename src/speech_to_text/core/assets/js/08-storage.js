
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

  // Set once the browser has refused a write, so the warning is shown a single
  // time rather than on every debounce tick from then on.
  var saveFailedWarned = false;

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
        // Almost always the quota. Chrome pools every file:// document into
        // one origin, so this page shares a few megabytes with every other
        // transcript ever opened on this machine, and nothing evicts the
        // older ones - each run mints a fresh doc id and its own key.
        //
        // The status box alone is not enough here. It swaps one pre-rendered
        // label for another in a corner, and the reader is looking at the text
        // they are editing. Losing an afternoon's proofreading to a colour
        // change is the one failure this document cannot afford, so it also
        // says so out loud and names the way out: export a copy, which writes
        // a real file and does not touch the quota.
        setStatus('error');
        if (!saveFailedWarned) {
          saveFailedWarned = true;
          showToast(t('save_failed',
            'Could not save in the browser - use "Save a copy" to keep your edits.'));
        }
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
