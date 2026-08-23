  // ------------------------------------------------------------------ audio

  // bindAudio() used to be 222 lines with five nested functions closing over
  // six independent module-level-looking variables (current, currentSection,
  // boundEnd, scrubbing, lastSweep, playing) - a module wearing a "binder"
  // function's name. Pulled apart into this shared, explicit playback-state
  // object plus a handful of top-level helpers that take the pieces they
  // need as arguments, so each one's signature says what it touches instead
  // of a reader having to hold the whole closure in their head. bindAudio()
  // itself is now just the event wiring.
  function createPlayerState() {
    return {
      current: null,        // filename of the recording currently loaded
      currentSection: null, // the .source element that recording belongs to
      // The end of the range a .ts click asked to hear, or null when
      // playback is free-running (the reader pressed the toggle, or nothing
      // bounded has been clicked yet).
      boundEnd: null,
      // Set on the seek input's own 'input' event, read by the throttled
      // timeupdate sweep so it never overwrites seek.value while a drag is
      // in progress - the same "don't fight the control the reader's
      // fingers are on" rule the search box's re-entrancy guard follows.
      scrubbing: false,
      lastSweep: 0,          // Date.now() of the last throttled highlight sweep
      playing: null,         // the .turn currently marked data-playing
    };
  }

  function formatPlayerTime(s) {
    var m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ':' + (r < 10 ? '0' : '') + r;
  }

  // Drives the track's left-to-right fill (see .seek in transcript.css:
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
  // core/formatting.py - a neutral "/" between two LTR runs, inside an RTL
  // document, needs the same LRI/PDI guard or it can reorder the same way
  // an un-isolated timestamp used to.
  function updatePlayerReadout(audio, timeEl) {
    var duration = isFinite(audio.duration) ? audio.duration : 0;
    timeEl.textContent = '⁦' + formatPlayerTime(audio.currentTime) + ' / ' + formatPlayerTime(duration) + '⁩';
  }

  // timeupdate fires several times a second. The clock is cheap, but
  // re-deciding which turn is playing walks the section, so that part is
  // throttled to roughly four times a second (see bindAudio()'s own
  // timeupdate handler for the throttle itself) - fast enough to feel live,
  // slow enough to stay off the main thread's budget.
  function highlightPlayingTurn(pstate, position) {
    // The section is held as an element reference rather than looked up by
    // its filename - a filename is arbitrary text and has no business being
    // spliced into a selector.
    var section = pstate.currentSection;
    if (!section) { return; }

    // The turn being spoken is the last one that started at or before now.
    var found = null;
    section.querySelectorAll('.turn').forEach(function (turn) {
      if (Number(turn.dataset.start) <= position) { found = turn; }
    });
    if (found === pstate.playing) { return; }

    if (pstate.playing) { delete pstate.playing.dataset.playing; }
    pstate.playing = found;
    if (pstate.playing) { pstate.playing.dataset.playing = 'true'; }
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
        // Clicking a timestamp is the one moment the readout has to update
        // before playback (and therefore the throttled timeupdate handler)
        // has necessarily started - a reader glancing at "0:32 / 3:11" right
        // after the click, before any audio has actually played a frame,
        // should not see a stale "0:00 / 3:11" left over from load.
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

      // The CSS strips the button chrome and pointer cursor (see
      // .source[data-no-audio] .ts), but a visual change alone leaves the
      // control reachable by Tab and announced as a button to a screen
      // reader - both would still promise an action that no longer happens.
      // disabled removes it from the tab order and native click handling;
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

    // The range-stop check runs on every timeupdate tick, unthrottled,
    // unlike the highlight sweep below - it is a single number comparison,
    // cheap enough to run every time, and it has to: at the ~250ms
    // resolution the throttled sweep runs at, a short turn could finish
    // playing before the throttle ever looked, overshooting well past its
    // end. A setTimeout timed to the range's length was the other option
    // and was rejected - it would race whatever called pause() or changed
    // currentTime in between, firing a stale stop after a reader had
    // already sought elsewhere. Overshoot here is bounded by one
    // timeupdate tick, which reads as "stopped right around there," not as
    // a bug.
    audio.addEventListener('timeupdate', function () {
      updatePlayerReadout(audio, timeEl);
      // Left alone mid-drag: the seek input's own 'input' handler is already
      // setting audio.currentTime from seek.value, so timeupdate writing
      // seek.value back from audio.currentTime in the same tick would just
      // be echoing the drag back at itself - harmless in the best case,
      // fighting the pointer in the worst.
      if (!pstate.scrubbing) {
        seek.value = String(audio.currentTime);
        updateSeekFill(seek);
      }

      if (pstate.boundEnd !== null && audio.currentTime >= pstate.boundEnd) {
        audio.pause();
        audio.currentTime = pstate.boundEnd;
        pstate.boundEnd = null;
      }

      var now = Date.now();
      if (now - pstate.lastSweep < 250) { return; }
      pstate.lastSweep = now;
      highlightPlayingTurn(pstate, audio.currentTime);
    });

    audio.addEventListener('pause', function () {
      if (pstate.playing) { delete pstate.playing.dataset.playing; }
      pstate.playing = null;
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
