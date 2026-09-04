  // --------------------------------------------------------------- outline

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
        // Instant feedback: the anchor jump and the observer that follows it
        // land on the same answer (see pickActiveFromGeometry), so this only
        // moves the highlight a few milliseconds earlier than it would move
        // anyway, rather than asserting something the heuristic then has to
        // be prevented from overruling.
        setActiveFile(a.dataset.file);
      });
    });

    // Which file is "current" is driven by the same observer that drives
    // the outline's own active marker - one source of truth rather than a
    // second scroll handler that could disagree with it. rootMargin pulls
    // the effective viewport in from the top by the toolbar's height (so a
    // section sliding in under the sticky toolbar doesn't count as "in
    // view" a frame early) and from the bottom by 60%, so the section
    // occupying the *upper* portion of the screen - the one the reader is
    // actually reading - wins over one just barely peeking in at the
    // bottom edge.
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
      // This used to keep an `intersecting` map, writing each entry's
      // isIntersecting into it and picking the smallest file index still
      // marked true. The map was an incrementally-built cache trusted
      // forever, and that is what broke clicking a file link: the browser
      // samples intersections at a rendering step but runs the callback
      // afterwards, so an anchor jump lands BETWEEN the two and the callback
      // arrives carrying the pre-jump truth. Clicking file 2 wrote a stale
      // "file 1 is intersecting" into the map one tick after the click
      // handler had correctly highlighted file 2, and since the picker takes
      // the LOWEST index marked true, the stale entry won. Nothing then
      // corrected it: no further threshold is crossed until the next scroll,
      // so the wrong highlight stuck until the reader clicked a second time
      // (which no longer scrolls, being already at the anchor, so no
      // observer callback fires to overwrite the click handler).
      //
      // Reading rects here cannot go stale by construction - it is measured
      // when it is used. The cost is one getBoundingClientRect per file per
      // callback, and callbacks only fire when a section actually crosses
      // the band, so this is a handful of reads on an event that is already
      // rare.
      function pickActiveFromGeometry() {
        // The reading line, normally the bottom edge of the band the
        // observer's rootMargin describes.
        //
        // At the very end of the document it moves to the bottom of the
        // viewport instead. Once the page cannot scroll any further, a short
        // final file can be fully on screen with its top edge still BELOW
        // the reading line - measured here at a 772px-tall window, the last
        // file's top sits at 361px against a line at 309px - so no rule of
        // the form "the last section above the line" can ever name it while
        // the line stays put. Dropping the line to the viewport bottom in
        // that one state makes "the last section the reader can see" the
        // answer, which is what arriving at the end of the document actually
        // means.
        var line = (window.innerHeight + window.scrollY >=
                    document.documentElement.scrollHeight - 2)
          ? window.innerHeight
          : window.innerHeight * 0.4;

        // The current file is the LAST one whose heading the reader has
        // reached - the section furthest down the document whose top edge is
        // above the reading line.
        //
        // The rule used to be "the topmost section intersecting the band",
        // and that is what made clicking the last file in the list land on
        // its predecessor. A jump to the final file scrolls as far as the
        // page can go, which is usually not far enough to lift that file
        // into the band at all, while the file before it still sits in the
        // band - so the topmost-in-band rule kept naming the wrong one, and
        // no amount of further scrolling could change its mind because the
        // page had already hit its end.
        //
        // A pin ("the clicked file wins until the reader scrolls away") was
        // built first and thrown away: it needed the post-jump scroll
        // position, which meant a requestAnimationFrame, and rAF does not
        // run in a background or occluded tab - so the pin could never
        // release there and the highlight froze permanently, which is a
        // worse failure than the one being fixed. Measuring against the
        // reading line needs no such state: it is a pure function of the
        // current layout, gives the same answer for a click and for a scroll
        // that ends in the same place, and names the last file correctly
        // because that file's top edge does rise above the line even when
        // the page runs out of scroll.
        var best = null;
        sources.forEach(function (section) {
          if (section.getBoundingClientRect().top >= line) { return; }
          var index = Number(section.dataset.file);
          if (best === null || index > best) { best = index; }
        });
        // Nothing has reached the line yet (the reader is above the first
        // section, e.g. at the very top of a document with a tall toolbar):
        // the first file is the only sensible answer.
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
      // exactly as in-band or out-of-band as it already was. No crossing, no
      // callback, and the highlight stayed on the previous file.
      //
      // The original code avoided a scroll handler on the grounds that it
      // would be a second source of truth able to disagree with the
      // observer. That objection no longer applies: both triggers call the
      // same pure function, which reads live layout and holds no state
      // between calls, so they cannot reach different answers - they can
      // only reach the same one at different moments. Resize matters for the
      // same reason (the line is a fraction of the viewport height).
      //
      // Unthrottled on purpose: the work is one getBoundingClientRect per
      // file, on documents that hold a handful of files, which is cheaper
      // than the bookkeeping a throttle would add.
      window.addEventListener('scroll', pickActiveFromGeometry, { passive: true });
      window.addEventListener('resize', pickActiveFromGeometry);
    }
  }
