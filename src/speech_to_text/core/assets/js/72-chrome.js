
  // An explicit data-theme wins; with none set the page follows
  // @media(prefers-color-scheme) in core/assets/css/, so this reads matchMedia
  // back rather than assuming light - the toggle's label has to name the next
  // state correctly even before anyone touches it.
  function effectiveTheme() {
    var explicit = document.documentElement.dataset.theme;
    if (explicit === 'dark' || explicit === 'light') { return explicit; }
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
      ? 'dark' : 'light';
  }

  // The button names the action, not the current state ("מצב כהה" while light,
  // "מצב בהיר" while dark - the doc_theme_light/doc_theme_dark keys in
  // gui/i18n.py), so the label flips on every theme change, including once on
  // init in case the server-rendered label guessed the system preference wrong.
  function syncThemeLabel() {
    var btn = document.getElementById('toggle-theme');
    if (!btn) { return; }
    var label = btn.querySelector('span');
    var next = effectiveTheme() === 'dark' ? btn.dataset.labelLight : btn.dataset.labelDark;
    if (label && next) { label.textContent = next; }
  }

  function bindSearchControls() {
    var searchInput = document.getElementById('search');
    if (searchInput) {
      var timer = null;
      searchInput.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { runSearch(searchInput.value.trim()); }, 200);
      });
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { searchInput.value = ''; clearSearch(); }
        if (e.key === 'Enter') {
          e.preventDefault();
          if (e.shiftKey) { prevMatch(); } else { nextMatch(); }
        }
      });
    }

    var next = document.getElementById('search-next');
    var prev = document.getElementById('search-prev');
    if (next) { next.addEventListener('click', nextMatch); }
    if (prev) { prev.addEventListener('click', prevMatch); }
  }

  function bindThemeToggle() {
    var theme = document.getElementById('toggle-theme');
    if (!theme) { return; }
    theme.addEventListener('click', function () {
      var nextTheme = effectiveTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = nextTheme;
      state.theme = nextTheme;
      syncThemeLabel();
      save();
    });
  }

  function bindUnloadGuard() {
    window.addEventListener('beforeunload', function (e) {
      // Only nag when there is real work no file on disk contains yet. Renames
      // count as much as text edits.
      if (!exported && hasLocalChanges()) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  function isTextEntry(node) {
    return !!node && (node.isContentEditable
      || node.tagName === 'INPUT' || node.tagName === 'TEXTAREA');
  }

  function bindGlobalShortcuts() {
    document.addEventListener('keydown', function (e) {
      // The target can be retargeted, or be the document itself for a
      // programmatic dispatch, while activeElement always reflects where the
      // caret is. Consulting only one of them swallows a typed "/" mid-word.
      var typing = isTextEntry(e.target) || isTextEntry(document.activeElement);

      // Ctrl/Cmd+S is what fingers do when they want the file written. There is
      // no file to write, so it exports, which is the nearest true thing.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        exportCopy();
        return;
      }
      // "/" jumps to search, but not while the reader is mid-word.
      if (e.key === '/' && !typing) {
        e.preventDefault();
        var box = document.getElementById('search');
        if (box) { box.focus(); }
      }
    });
  }

  function bindChrome() {
    bindSearchControls();

    var flags = document.getElementById('toggle-flags');
    if (flags) {
      flags.addEventListener('click', function () { setFlags(!state.flags); save(); });
    }

    bindThemeToggle();

    var exportBtn = document.getElementById('export');
    if (exportBtn) { exportBtn.addEventListener('click', exportCopy); }

    bindUnloadGuard();
    bindGlobalShortcuts();
  }
