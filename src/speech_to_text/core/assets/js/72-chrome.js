  // ----------------------------------------------------------------- chrome

  // The theme actually in effect right now: an explicit data-theme wins
  // (either restored from a previous session or set by this page's own
  // toggle); with none set, the page is following the system/browser
  // preference via the @media(prefers-color-scheme) block in the stylesheet (core/assets/css/),
  // which this reads back from matchMedia rather than assuming light - the
  // button's label has to name the *next* state correctly even when nobody
  // has touched the toggle yet.
  function effectiveTheme() {
    var explicit = document.documentElement.dataset.theme;
    if (explicit === 'dark' || explicit === 'light') { return explicit; }
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
      ? 'dark' : 'light';
  }

  // The button names the action, not the current state ("מצב כהה" while
  // light, "מצב בהיר" while dark - see the doc_theme_light/doc_theme_dark
  // keys in gui/i18n.py), so its label has to flip every time the effective
  // theme changes: on click, and once on init in case the system preference
  // was already dark and core/formatting's server-rendered "dark mode" label
  // guessed wrong.
  function syncThemeLabel() {
    var btn = document.getElementById('toggle-theme');
    if (!btn) { return; }
    var label = btn.querySelector('span');
    var next = effectiveTheme() === 'dark' ? btn.dataset.labelLight : btn.dataset.labelDark;
    if (label && next) { label.textContent = next; }
  }

  // bindChrome() used to poke `matchIndex` directly in three places to move
  // search - nextMatch()/prevMatch() (see the search section) are what it
  // calls instead now, so how search steps is defined in exactly one place.
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
      // Only nag when there is real work that no file on disk contains yet.
      // Renames count as much as text edits - both are lost if this browser's
      // storage is cleared and no copy was ever exported.
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
      // Both the event target and the focused element are consulted: the
      // target can be retargeted (or be the document itself, for a
      // programmatic dispatch), while activeElement always reflects where the
      // caret actually is. Getting this wrong swallows a typed "/" mid-word.
      var typing = isTextEntry(e.target) || isTextEntry(document.activeElement);

      // Ctrl/Cmd+S is what everyone's fingers do when they want the file
      // written. There is no file to write, so it triggers the export, which
      // is the nearest true thing.
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

  // bindChrome() used to be 79 lines doing four unrelated jobs (search,
  // flags, theme, the unload guard/keyboard shortcuts) in one function body
  // - split into the four binders above, each named for the one job it
  // does, so this is now just the list of what runs on init.
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
