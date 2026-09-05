
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

  // Speaker roster first, then which speaker each turn belongs to, then text
  // edits, then the labels that read all of it back - each step depends on
  // the DOM state the one before it left.
  applySpeakerState();
  applyAssignments();
  // A bubble's override is relative to its cluster's speaker, so every
  // cluster has to be settled by applyAssignments() first.
  applyLineAssignments();
  applyEdits();
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

  // Restored edits live in this browser, not in any file, so open on "local"
  // rather than a reassuring "Saved" that would be a lie.
  exported = !hasLocalChanges();
  setStatus(exported ? 'saved' : 'local');
