  // Which file's speakers panel is shown and which outline-files link reads
  // as current - kept in one place so the IntersectionObserver below and a
  // manual file-link click (bindOutline()) can't drift into disagreeing
  // about "the current file".
  function setActiveFile(fileIndex) {
    document.querySelectorAll('.outline-file').forEach(function (a) {
      var isCurrent = a.dataset.file === String(fileIndex);
      if (isCurrent) { a.setAttribute('aria-current', 'true'); } else { a.removeAttribute('aria-current'); }
    });
    document.querySelectorAll('.outline-speakers .speakers').forEach(function (panel) {
      panel.classList.toggle('active', panel.dataset.file === String(fileIndex));
    });
  }

  function bindOutline() {
    var outline = document.getElementById('outline');

    // No <aside> at all (a single file with no speakers - see
    // _render_outline_html()'s early return) - nothing here to wire up.
    if (!outline) { return; }

    // Gates the CSS rule that hides every non-current speakers panel (see
    // .outline.js-ready in the stylesheet (core/assets/css/)) - added only once script is
    // actually running, so a JavaScript-disabled open keeps every panel
    // visible instead of losing all but the first to a rule with nothing
    // left to un-hide them.
    outline.classList.add('js-ready');

    outline.querySelectorAll('.outline-file').forEach(function (a) {
      a.addEventListener('click', function () {
        // Instant feedback only: the anchor jump and the observer that
        // follows it land on the same answer (see pickActiveFromGeometry),
        // so this asserts nothing the geometry then has to be stopped from
        // overruling.
        setActiveFile(a.dataset.file);
      });
    });

    // rootMargin pulls the effective viewport in from the top by the
    // toolbar's height (so a section sliding in under the sticky toolbar
    // doesn't count as "in view" a frame early) and from the bottom by 60%,
    // so the section occupying the *upper* portion of the screen - the one
    // the reader is actually reading - wins over one just barely peeking in
    // at the bottom edge.
    if (window.IntersectionObserver) {
      var sources = document.querySelectorAll('.source');

      function currentToolbarHeight() {
        return parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--toolbar-height')
        ) || 0;
      }

      // The observer is only a "something moved, look again" trigger here.
      // The answer itself comes from reading the sections' real geometry at
      // the moment of the decision, NOT from entry.isIntersecting.
      //
      // entry.isIntersecting can arrive stale: the browser samples
      // intersections at a rendering step but runs the callback afterwards,
      // so an anchor jump lands BETWEEN the two and the callback carries the
      // pre-jump truth. Cached into a map, that stale value sticks - no
      // further threshold is crossed until the next scroll, so nothing
      // corrects it and a file-link click lands on the wrong file.
      //
      // Reading rects here cannot go stale by construction - it is measured
      // when it is used. The cost is one getBoundingClientRect per file per
      // callback, on an event that only fires when a section crosses the
      // band.
      function pickActiveFromGeometry() {
        // The reading line, normally the bottom edge of the band the
        // observer's rootMargin describes.
        //
        // At the very end of the document it moves to the bottom of the
        // viewport instead. Once the page cannot scroll any further, a short
        // final file can be fully on screen with its top edge still BELOW
        // the reading line - measured at a 772px-tall window, the last
        // file's top sits at 361px against a line at 309px - so no rule of
        // the form "the last section above the line" can ever name it while
        // the line stays put. Dropping the line to the viewport bottom in
        // that one state makes the answer "the last section the reader can
        // see", which is what reaching the end of the document means.
        var line = (window.innerHeight + window.scrollY >=
                    document.documentElement.scrollHeight - 2)
          ? window.innerHeight
          : window.innerHeight * 0.4;

        // The current file is the LAST one whose heading the reader has
        // reached - the section furthest down the document whose top edge is
        // above the reading line.
        //
        // Not "the topmost section intersecting the band": a jump to the
        // final file scrolls as far as the page can go, which is usually not
        // far enough to lift that file into the band at all while the file
        // before it still sits in it, so that rule names the predecessor and
        // no further scrolling can change its mind.
        //
        // A pin ("the clicked file wins until the reader scrolls away") was
        // rejected: it needs the post-jump scroll position, which means a
        // requestAnimationFrame, and rAF does not run in a background or
        // occluded tab - so the pin could never release there and the
        // highlight would freeze permanently. Measuring against the reading
        // line needs no such state: it is a pure function of the current
        // layout, so a click and a scroll ending in the same place give the
        // same answer.
        var best = null;
        sources.forEach(function (section) {
          if (section.getBoundingClientRect().top >= line) { return; }
          var index = Number(section.dataset.file);
          if (best === null || index > best) { best = index; }
        });
        // Nothing has reached the line yet (the reader is above the first
        // section): the first file is the only sensible answer.
        setActiveFile(best === null ? 0 : best);
      }

      var observer = new IntersectionObserver(
        pickActiveFromGeometry,
        { rootMargin: '-' + (currentToolbarHeight() + 1) + 'px 0px -60% 0px', threshold: 0 }
      );
      sources.forEach(function (section) { observer.observe(section); });

      // The observer alone is not a sufficient trigger, which is worth
      // spelling out because it looks like it should be: it only fires when
      // a section crosses the band's edge, and the answer above can change
      // without any such crossing. Scrolling up from the end of a document
      // is the case that proved it - the last file leaves the "no scroll
      // left" state, which moves the reading line, while every section stays
      // exactly as in-band or out-of-band as it already was.
      //
      // A second trigger is not a second source of truth here: both call the
      // same pure function, which reads live layout and holds no state, so
      // they can only reach the same answer at different moments. Resize
      // matters too - the line is a fraction of the viewport height.
      //
      // Unthrottled on purpose: one getBoundingClientRect per file, on
      // documents holding a handful of files, is cheaper than the
      // bookkeeping a throttle would add.
      window.addEventListener('scroll', pickActiveFromGeometry, { passive: true });
      window.addEventListener('resize', pickActiveFromGeometry);
    }
  }
