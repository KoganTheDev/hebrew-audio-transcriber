
  function exportCopy() {
    clearSearch();
    var wasFlagged = state.flags;
    if (wasFlagged) { setFlags(false); }

    // Serialising reads attributes, but typing only updates properties, so
    // form state has to be written back before it can survive the export.
    bakeFormState();

    // Strip transient view state - a half-typed query, an audio path that only
    // meant something on this machine - so the copy opens at rest, not frozen
    // mid-session.
    var restore = resetTransientState();

    // The live DOM already holds the edits and names, so serialising it is the
    // export: the copy is a working editor with the same doc id.
    var html = '<!doctype html>\n' + document.documentElement.outerHTML;
    restore();
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (DATA.filename || 'transcript') + ' (edited).html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    if (wasFlagged) { setFlags(true); }
    exported = true;
    setStatus('saved');
  }

  function bakeFormState() {
    // Without this the copy carries speaker names in the turn labels but an
    // empty name box, and on a machine with no saved state the first edit
    // would read that empty box and reset the name to its fallback.
    document.querySelectorAll('.speaker-name').forEach(function (input) {
      input.setAttribute('value', input.value);
    });
    // Per-bubble speaker overrides (state.assignLine, js/24-speakers-menus.js)
    // need no baking: paintBubbleOverride() writes them as attributes and text
    // nodes, which outerHTML already carries verbatim.
    document.querySelectorAll('.plain input[type="checkbox"]').forEach(function (box) {
      if (box.checked) {
        box.setAttribute('checked', '');
      } else {
        box.removeAttribute('checked');
      }
    });
  }

  function resetTransientState() {
    var searchInput = document.getElementById('search');
    var player = document.getElementById('player');
    var audio = document.getElementById('audio');
    var count = document.getElementById('search-count');

    var previous = {
      query: searchInput ? searchInput.value : '',
      audioSrc: audio ? audio.getAttribute('src') : null,
      playerHidden: player ? player.hidden : true
    };

    if (searchInput) { searchInput.value = ''; }
    if (count) { count.textContent = ''; }
    if (player) { player.hidden = true; }
    // Remove the attribute rather than blanking it: src="" resolves to the
    // document URL, which makes the browser try to play the HTML itself.
    if (audio) { audio.removeAttribute('src'); }

    return function () {
      if (searchInput) { searchInput.value = previous.query; }
      if (player) { player.hidden = previous.playerHidden; }
      if (audio && previous.audioSrc) { audio.setAttribute('src', previous.audioSrc); }
    };
  }
