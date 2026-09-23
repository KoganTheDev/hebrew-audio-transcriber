
  // The sticky file bar sits below the toolbar (.file-bar in
  // core/assets/css/), which wraps onto a second line under ~480px. A fixed
  // number would drift out of sync, so the height is measured and republished
  // as the custom property the CSS reads.
  function syncToolbarHeight() {
    var toolbar = document.querySelector('.toolbar');
    if (!toolbar) { return; }
    document.documentElement.style.setProperty('--toolbar-height', toolbar.offsetHeight + 'px');
  }

  // Tracks input modality on <html> as data-kbd, for the .body/.plain-body
  // focus ring (see the STATED EXCEPTION comment in core/assets/css/).
  // :focus-visible alone cannot do this: Chromium matches it on a
  // contenteditable element for a mouse click too, lighting the ring up when a
  // reader merely clicks in to select text. Tab is the one key that can move
  // focus without some other keydown listener on this page already handling
  // it, and the flag is set rather than toggled off on other keys so a
  // keyboard session survives, say, an arrow key inside the seek control.
  // pointerdown, not click: it fires before the resulting focus event, so the
  // flag is already clear by the time :focus paints.
  function bindKeyboardModality() {
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Tab') { document.documentElement.setAttribute('data-kbd', 'true'); }
    });
    document.addEventListener('pointerdown', function () {
      document.documentElement.removeAttribute('data-kbd');
    });
  }
