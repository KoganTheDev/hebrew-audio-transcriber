  // ------------------------------------------------------------------- init

  load();
  bindKeyboardModality();
  bindEditing();
  bindSpeakers();
  bindMenus();
  bindPlain();
  bindAudio();
  bindChrome();
  bindOutline();
  bindHelp();

  syncToolbarHeight();
  window.addEventListener('resize', syncToolbarHeight);

  // Speaker roster first (added speakers, recolours), then which speaker
  // each turn belongs to, then text edits, then the labels that read all of
  // it back - each step depends on the DOM state the one before it left.
  applySpeakerState();
  applyAssignments();
  applyEdits();
  // applyAssignments() has already replayed any saved reassignments by this
  // point, so .turn[data-speaker] reflects the real, final state - applying
  // names now is what makes a reloaded page's labels match a session's own
  // reassignments from before reload.
  document.querySelectorAll('.speakers').forEach(function (s) {
    applyNames(s.dataset.file);
  });

  Object.keys(state.opts).forEach(function (file) {
    var panel = document.querySelector('.source[data-file="' + file + '"] .plain');
    if (!panel) { return; }
    var ts = panel.querySelector('.opt-ts');
    var spk = panel.querySelector('.opt-spk');
    if (ts) { ts.checked = state.opts[file].ts; }
    if (spk) { spk.checked = state.opts[file].spk; }
  });
  document.querySelectorAll('.source').forEach(rebuildPlain);

  if (state.theme) { document.documentElement.dataset.theme = state.theme; }
  syncThemeLabel();
  if (state.flags) { setFlags(true); }

  // Restored edits are in this browser, not in any file - assume the worst and
  // say so, rather than opening on a reassuring "Saved" that might be a lie.
  exported = !hasLocalChanges();
  setStatus(exported ? 'saved' : 'local');
