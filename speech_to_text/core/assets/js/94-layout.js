  // ---------------------------------------------------------------- layout

  // The sticky file bar sits below the toolbar (see .file-bar in
  // transcript.css), which wraps onto a second line under ~480px - a fixed
  // number here would drift out of sync with that the first time the
  // toolbar's own height changed, so it's measured instead and republished
  // as a custom property the CSS reads.
  function syncToolbarHeight() {
    var toolbar = document.querySelector('.toolbar');
    if (!toolbar) { return; }
    document.documentElement.style.setProperty('--toolbar-height', toolbar.offsetHeight + 'px');
  }

  // Tracks input modality on <html> as data-kbd, for the .body/.plain-body
  // focus ring (see the STATED EXCEPTION comment at the top of
  // transcript.css). :focus-visible alone cannot do this: Chromium matches
  // it on a contenteditable element for a mouse click too, which is the
  // exact bug being fixed (the ring lighting up when a reader merely clicks
  // in to select text). Tab is the one key that can move focus without
  // already being handled by some other keydown listener on this page, and
  // is set rather than toggled off on other keys - a reader tabbing through
  // controls and then pressing, say, an arrow key inside the seek control
  // should not lose the flag mid-keyboard-session. pointerdown, not click:
  // it fires before the resulting focus event, so the flag is already clear
  // by the time :focus paints.
  function bindKeyboardModality() {
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Tab') { document.documentElement.setAttribute('data-kbd', 'true'); }
    });
    document.addEventListener('pointerdown', function () {
      document.documentElement.removeAttribute('data-kbd');
    });
  }
