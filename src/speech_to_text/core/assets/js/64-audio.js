  // Playback state, shared explicitly between the helpers below rather than
  // captured in one large closure, so each signature says what it touches.
  function createPlayerState() {
    return {
      current: null,        // filename of the recording currently loaded
      currentSection: null, // the .source element that recording belongs to
      // The end of the range a .ts click asked to hear, or null when
      // playback is free-running (the reader pressed the toggle, or nothing
      // bounded has been clicked yet).
      boundEnd: null,
      // Set on the seek input's own 'input' event, read by the timeupdate
      // handler so it never overwrites seek.value mid-drag.
      scrubbing: false,
    };
  }

  function formatPlayerTime(s) {
    var m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ':' + (r < 10 ? '0' : '') + r;
  }

  // Drives the track's left-to-right fill (see .seek in the stylesheet (core/assets/css/):
  // the gradient is painted from --seek-fill, not from the input's own
  // value/max, because browsers disagree on whether a range's native fill
  // respects a forced `direction: ltr`). A percentage string, not a bare
  // number, since it is written straight into a CSS custom property that
  // feeds a linear-gradient() stop.
  function updateSeekFill(seek) {
    var max = Number(seek.max) || 0;
    var pct = max > 0 ? (Number(seek.value) / max) * 100 : 0;
    seek.style.setProperty('--seek-fill', pct + '%');
  }

  // Isolated LTR digits, same shape as format_range()'s "M:SS - M:SS" in
  // core/formatting - a neutral "/" between two LTR runs, inside an RTL
  // document, needs the same LRI/PDI guard or it can reorder.
  function updatePlayerReadout(audio, timeEl) {
    var duration = isFinite(audio.duration) ? audio.duration : 0;
    timeEl.textContent = '⁦' + formatPlayerTime(audio.currentTime) + ' / ' + formatPlayerTime(duration) + '⁩';
  }

  // Driven off the audio element's own play/pause events, not off the
  // toggle button's click handler, so the glyph and label are correct
  // even when nothing here caused the pause - the range-bound stop in the
  // timeupdate handler below calls audio.pause() directly, and a reader
  // watching the button would otherwise still see "pause" after playback
  // had actually stopped on its own.
  function syncToggleGlyph(audio, toggle) {
    var toggleUse = toggle.querySelector('use');
    var playingNow = !audio.paused && !audio.ended;
    if (toggleUse) { toggleUse.setAttribute('href', playingNow ? '#i-pause' : '#i-play'); }
    // Swapped alongside the glyph, not left behind: a button whose icon
    // shows "pause" while its accessible name still says "play" is worse
    // than not swapping at all - a screen reader user would be told the
    // opposite of what a sighted reader sees.
    toggle.setAttribute('aria-label', playingNow ? t('pause', 'Pause') : t('play_pause', 'Play'));
  }

  function bindAudio() {
    var audio = document.getElementById('audio');
    var player = document.getElementById('player');
    if (!audio || !player) { return; }

    var fileEl = document.getElementById('player-file');
    var timeEl = document.getElementById('player-time');
    var toggle = document.getElementById('player-toggle');
    var seek = document.getElementById('player-seek');
    var pstate = createPlayerState();

    // Every ".ts" on the page, not just the turn header's own <button> - a
    // bubble's <span class="ts"> (see _render_bubble_html() in
    // core/formatting/document.py) is the same shape of click target, one
    // sentence wide instead of up to 30s. It carries no data-start/data-end
    // of its own, though: those live on the wrapping .bubble (unconditionally,
    // regardless of whether the visible timestamp span is even rendered - see
    // that same function's docstring), so a bubble click has to read its
    // range from the ancestor, while a header click still reads its own.
    document.querySelectorAll('.ts').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var section = btn.closest('.source');
        var file = section.dataset.audio;
        if (!file) { return; }

        var bubble = btn.closest('.bubble');
        var start = Number(bubble ? bubble.dataset.start : btn.dataset.start);
        var end = Number(bubble ? bubble.dataset.end : btn.dataset.end);

        player.hidden = false;
        fileEl.textContent = file;
        if (pstate.current !== file) {
          pstate.current = file;
          pstate.currentSection = section;
          audio.src = encodeURIComponent(file);
          seek.max = '0';
        }
        audio.currentTime = start;
        pstate.boundEnd = end;
        seek.value = String(audio.currentTime);
        updateSeekFill(seek);
        // The one moment the readout has to update before playback, and so
        // before any timeupdate tick has fired: a reader glancing at the
        // clock right after the click must not see a stale value from load.
        updatePlayerReadout(audio, timeEl);
        audio.play().catch(function () { /* the error listener handles it */ });
      });
    });

    audio.addEventListener('loadedmetadata', function () {
      seek.max = String(audio.duration);
      updatePlayerReadout(audio, timeEl);
      updateSeekFill(seek);
    });

    seek.addEventListener('input', function () {
      pstate.scrubbing = true;
      audio.currentTime = Number(seek.value);
      // A deliberate seek overrides whatever range a .ts click asked to stay
      // inside - dragging the scrubber past data-end must not snap the
      // playhead back, the same "manual control wins" rule the toggle
      // button's own click handler already applies to a manual resume.
      pstate.boundEnd = null;
      updatePlayerReadout(audio, timeEl);
      updateSeekFill(seek);
    });
    seek.addEventListener('change', function () { pstate.scrubbing = false; });

    audio.addEventListener('error', function () {
      // The audio was moved away from the transcript, or the container is one
      // the browser cannot play (.mkv, for instance). Playback is an extra, so
      // it removes itself rather than showing a broken control.
      player.hidden = true;
      if (!pstate.currentSection) { return; }

      // Only the recording that actually failed is marked. A batch routinely
      // mixes files that play with ones that do not - a missing .mkv must not
      // take the other transcripts' playback down with it, and this handler
      // fires per failed load, so a document-wide flag would be permanent
      // after the first bad file.
      pstate.currentSection.dataset.noAudio = 'true';

      // The CSS strips the button chrome (see .source[data-no-audio] .ts),
      // but a visual change alone leaves the control reachable by Tab and
      // announced as a button. disabled takes it out of the tab order;
      // aria-disabled is set alongside it because some assistive tech
      // announces "dimmed"/"unavailable" from aria-disabled specifically.
      pstate.currentSection.querySelectorAll('.ts').forEach(function (btn) {
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
      });

      // Let the next click start clean rather than short-circuiting on the
      // src it failed to load.
      pstate.current = null;
      pstate.currentSection = null;
      pstate.boundEnd = null;
      seek.max = '0';
      seek.value = '0';
      updateSeekFill(seek);
    });

    // The range-stop check runs on every timeupdate tick - it is a single
    // number comparison, cheap enough to run every time, and it has to run
    // that often: a short turn can be over in well under a second, so any
    // coarser sampling would overshoot past its end. A setTimeout timed to
    // the range's length was the other option and was rejected - it would
    // race whatever called pause() or changed currentTime in between,
    // firing a stale stop after a reader had already sought elsewhere.
    // Overshoot here is bounded by one timeupdate tick, which reads as
    // "stopped right around there," not as a bug.
    audio.addEventListener('timeupdate', function () {
      updatePlayerReadout(audio, timeEl);
      // Left alone mid-drag: the seek input's own 'input' handler is already
      // setting audio.currentTime from seek.value, so writing it back here
      // in the same tick would just fight the pointer.
      if (!pstate.scrubbing) {
        seek.value = String(audio.currentTime);
        updateSeekFill(seek);
      }

      if (pstate.boundEnd !== null && audio.currentTime >= pstate.boundEnd) {
        audio.pause();
        audio.currentTime = pstate.boundEnd;
        pstate.boundEnd = null;
      }
    });

    audio.addEventListener('play', function () { syncToggleGlyph(audio, toggle); });
    audio.addEventListener('pause', function () { syncToggleGlyph(audio, toggle); });

    toggle.addEventListener('click', function () {
      // A manual resume is the reader taking the wheel back - the range a
      // .ts click asked to stay inside no longer applies, or the toggle
      // would silently pause them again a moment later for no visible reason.
      pstate.boundEnd = null;
      if (audio.paused) { audio.play().catch(function () {}); } else { audio.pause(); }
    });
  }
