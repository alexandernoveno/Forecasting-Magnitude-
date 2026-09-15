/* ===========================================================================
   app.js

   Page behaviour that owns real data: the hero drum chart, drawn from the
   catalogue's own annual maxima, and the forecast lab that runs the exported
   models. The feature mathematics lives in forecast.js and is checked against
   Python by verify_bundle.cjs; nothing here reimplements it.

   Split out of index.html during the 2026 redesign so the markup stays
   readable and the browser can cache the logic separately.
   =========================================================================== */

(function () {
  "use strict";

  /* Annual maximum magnitude and event count, 1960 to 2026, straight from the
     cleaned catalogue. Each row is [year, maxMagnitude, eventCount]. */
  var RECORD = [
    [1960,6.7,12],[1961,6.1,6],[1962,6.5,39],[1963,6.3,41],[1964,5.8,66],
    [1965,5.9,101],[1966,7.7,71],[1967,6.0,80],[1968,7.3,123],[1969,6.1,181],
    [1970,7.8,228],[1971,6.5,125],[1972,7.3,282],[1973,6.5,212],[1974,5.9,156],
    [1975,6.3,374],[1976,7.9,167],[1977,7.2,252],[1978,5.7,307],[1979,5.9,213],
    [1980,6.3,274],[1981,5.7,254],[1982,5.6,213],[1983,6.5,309],[1984,6.1,224],
    [1985,6.1,122],[1986,6.2,105],[1987,6.0,175],[1988,5.6,111],[1989,6.6,111],
    [1990,7.8,506],[1991,6.4,296],[1992,7.3,165],[1993,6.6,136],[1994,7.1,172],
    [1995,7.3,285],[1996,7.0,375],[1997,6.7,251],[1998,7.0,250],[1999,6.8,262],
    [2000,6.4,221],[2001,7.2,163],[2002,6.8,137],[2003,6.8,168],[2004,6.2,204],
    [2005,6.9,174],[2006,7.1,237],[2007,6.6,243],[2008,6.5,415],[2009,7.5,303],
    [2010,7.1,360],[2011,6.7,243],[2012,7.6,488],[2013,7.2,358],[2014,6.4,408],
    [2015,6.1,256],[2016,6.5,297],[2017,7.2,325],[2018,7.0,256],[2019,6.9,526],
    [2020,6.6,465],[2021,7.1,480],[2022,7.0,542],[2023,7.4,860],[2024,7.1,697],
    [2025,7.4,700],[2026,7.8,272]
  ];

  var ROWS = 4;
  var canvas = document.getElementById("drum");
  if (!canvas) { return; }
  var ctx = canvas.getContext("2d");

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /* Deterministic jitter, so the trace is identical on every render. */
  function wobble(seed) {
    var x = Math.sin(seed * 12.9898) * 43758.5453;
    return x - Math.floor(x) - 0.5;
  }

  var width = 0, height = 0, progress = 0;

  function layout() {
    var box = canvas.getBoundingClientRect();
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(box.width, 240);
    height = Math.round(Math.min(Math.max(width * 0.62, 220), 340));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw() {
    var ink = token("--ink");
    var rule = token("--line");
    var accent = token("--accent");
    var mute = token("--mute");

    ctx.clearRect(0, 0, width, height);

    var padL = 42, padR = 10, padT = 10, padB = 8;
    var plotW = width - padL - padR;
    var rowH = (height - padT - padB) / ROWS;
    var perRow = Math.ceil(RECORD.length / ROWS);
    var shown = Math.floor(RECORD.length * progress);

    for (var r = 0; r < ROWS; r++) {
      var baseY = padT + rowH * r + rowH * 0.66;

      /* Drum baseline */
      ctx.strokeStyle = rule;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padL, Math.round(baseY) + 0.5);
      ctx.lineTo(padL + plotW, Math.round(baseY) + 0.5);
      ctx.stroke();

      var startIdx = r * perRow;
      var endIdx = Math.min(startIdx + perRow, RECORD.length);
      if (startIdx >= RECORD.length) { continue; }

      /* Row year label */
      ctx.fillStyle = mute;
      ctx.font = "9px 'IBM Plex Mono', monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(String(RECORD[startIdx][0]), padL - 8, baseY);

      /* The trace itself */
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1.1;
      ctx.lineJoin = "round";
      ctx.beginPath();

      var span = endIdx - startIdx;
      var stepX = plotW / (span || 1);
      var drewAny = false;

      for (var i = startIdx; i < endIdx; i++) {
        if (i >= shown) { break; }
        var rec = RECORD[i];
        var localX = padL + (i - startIdx + 0.5) * stepX;
        /* Amplitude from magnitude above the moderate threshold. */
        var amp = Math.max(rec[1] - 5.2, 0.05) / 2.7 * (rowH * 0.56);
        /* Sub-year texture, denser where the year logged more events. */
        var ticks = 9;
        for (var k = 0; k < ticks; k++) {
          var t = k / (ticks - 1);
          var x = localX + (t - 0.5) * stepX;
          var envelope = Math.exp(-Math.pow((t - 0.5) * 3.1, 2));
          var noise = wobble(i * 17.3 + k * 3.7) * 0.9 + Math.sin(k * 2.1 + i) * 0.55;
          var y = baseY - noise * amp * envelope;
          if (!drewAny) { ctx.moveTo(x, y); drewAny = true; }
          else { ctx.lineTo(x, y); }
        }
      }
      if (drewAny) { ctx.stroke(); }

      /* Mark the years that reached magnitude 7.5 or more. */
      for (var j = startIdx; j < endIdx; j++) {
        if (j >= shown) { break; }
        if (RECORD[j][1] < 7.5) { continue; }
        var mx = padL + (j - startIdx + 0.5) * stepX;
        var my = baseY - Math.max(RECORD[j][1] - 5.2, 0.05) / 2.7 * (rowH * 0.56) - 4;
        ctx.fillStyle = accent;
        ctx.beginPath();
        ctx.arc(mx, my, 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function render() { layout(); draw(); }

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var started = false;

  function run() {
    if (started) { return; }
    started = true;
    if (reduced.matches) { progress = 1; render(); return; }
    var t0 = null;
    var DURATION = 1700;
    function frame(ts) {
      if (t0 === null) { t0 = ts; }
      var p = Math.min((ts - t0) / DURATION, 1);
      progress = 1 - Math.pow(1 - p, 3);
      render();
      if (p < 1) { requestAnimationFrame(frame); }
    }
    requestAnimationFrame(frame);
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(render, 140);
  });

  /* Redraw when the viewer flips theme, so the trace picks up new tokens. */
  var scheme = window.matchMedia("(prefers-color-scheme: dark)");
  if (scheme.addEventListener) { scheme.addEventListener("change", function () { render(); }); }

  layout();
  progress = reduced.matches ? 1 : 0;
  draw();
  if (document.readyState === "complete") { run(); }
  else { window.addEventListener("load", run); }
})();


  /* =======================================================================
     Forecast lab
     Loads the exported models and the catalogue on demand, recomputes the 22
     features from the events on screen, and runs the selected model. The
     feature maths lives in forecast.js and is checked against Python by
     verify_bundle.cjs; nothing here reimplements it.
     ======================================================================= */
  (function () {
    var section = document.getElementById("lab");
    if (!section || typeof Forecast === "undefined") { return; }

    var el = {
      state: document.getElementById("state"),
      readout: document.getElementById("readout"),
      rows: document.getElementById("rows"),
      pick: document.getElementById("pick"),
      pickWrap: document.getElementById("pickWrap"),
      customWrap: document.getElementById("customWrap"),
      models: document.getElementById("models"),
      msg: document.getElementById("msg"),
      lat: document.getElementById("lat"),
      lon: document.getElementById("lon"),
      when: document.getElementById("when"),
    };
    var bundle = null, catalogue = null, loading = false, chosen = "random_forest";

    function source() {
      var hit = document.querySelector('input[name="source"]:checked');
      return hit ? hit.value : "recorded";
    }

    function setMsg(text, isError) {
      el.msg.textContent = text || "";
      el.msg.className = "msg" + (isError ? " msg--error" : "");
    }

    /* ---- data loading, with real loading and error states ---------------- */
    function load() {
      if (bundle || loading) { return Promise.resolve(); }
      loading = true;
      return Promise.all([
        fetch("model_bundle.json").then(function (r) {
          if (!r.ok) { throw new Error("model_bundle.json " + r.status); }
          return r.json();
        }),
        fetch("catalogue.json").then(function (r) {
          if (!r.ok) { throw new Error("catalogue.json " + r.status); }
          return r.json();
        }),
      ]).then(function (parts) {
        bundle = parts[0];
        catalogue = parts[1];
        loading = false;
        buildModelChoices();
        buildExampleChoices();
        syncSegments();
        loadExample(bundle.examples[0]);
        idle("Pick a sequence and a model, then forecast.");
      }).catch(function (err) {
        loading = false;
        el.readout.innerHTML = "";
        var p = document.createElement("p");
        p.className = "readout__state msg--error";
        p.textContent = "The models could not be loaded (" + err.message
          + "). Reload the page to try again.";
        el.readout.appendChild(p);
      });
    }

    function buildModelChoices() {
      el.models.innerHTML = "";
      Object.keys(bundle.models).forEach(function (key, i) {
        var m = bundle.models[key];
        var label = document.createElement("label");
        var input = document.createElement("input");
        input.type = "radio";
        input.name = "model";
        input.value = key;
        input.checked = i === 0;
        var span = document.createElement("span");
        span.innerHTML = m.label + ' <span class="rmse">' + m.rmse.toFixed(3) + "</span>";
        label.appendChild(input);
        label.appendChild(span);
        label.title = m.note + " Test RMSE " + m.rmse.toFixed(3) + " magnitude units.";
        input.addEventListener("change", function () { chosen = key; });
        el.models.appendChild(label);
      });
      chosen = Object.keys(bundle.models)[0];
    }

    function buildExampleChoices() {
      el.pick.innerHTML = "";
      bundle.examples.forEach(function (ex) {
        var opt = document.createElement("option");
        opt.value = ex.id;
        opt.textContent = ex.when + ", " + ex.epicentre[0].toFixed(2) + " N "
          + ex.epicentre[1].toFixed(2) + " E, " + ex.events.length + " foreshocks";
        el.pick.appendChild(opt);
      });
      el.pick.addEventListener("change", function () {
        var ex = bundle.examples.filter(function (e) { return e.id === el.pick.value; })[0];
        if (ex) { loadExample(ex); }
      });
    }

    /* ---- the event editor ------------------------------------------------ */
    var COLUMNS = [
      { key: "before", step: "0.01", min: "0", max: "14" },
      { key: "mag", step: "0.1", min: "0", max: "10" },
      { key: "lat", step: "0.01", min: "0", max: "25" },
      { key: "lon", step: "0.01", min: "110", max: "140" },
      { key: "depth", step: "1", min: "0", max: "750" },
    ];

    function addRow(values) {
      var tr = document.createElement("tr");
      COLUMNS.forEach(function (col) {
        var td = document.createElement("td");
        var input = document.createElement("input");
        input.type = "number";
        input.step = col.step;
        input.min = col.min;
        input.max = col.max;
        input.dataset.key = col.key;
        input.value = values ? values[col.key] : "";
        input.setAttribute("aria-label", col.key);
        td.appendChild(input);
        tr.appendChild(td);
      });
      var last = document.createElement("td");
      var del = document.createElement("button");
      del.type = "button";
      del.className = "rowdel";
      del.textContent = "x";
      del.setAttribute("aria-label", "Remove this event");
      del.addEventListener("click", function () { tr.remove(); });
      last.appendChild(del);
      tr.appendChild(last);
      el.rows.appendChild(tr);
    }

    function loadExample(ex) {
      el.rows.innerHTML = "";
      ex.events.forEach(function (e) {
        addRow({ before: e.before.toFixed(2), mag: e.mag, lat: e.lat, lon: e.lon, depth: e.depth });
      });
      el.lat.value = ex.epicentre[0];
      el.lon.value = ex.epicentre[1];
      if (ex.iso) { el.when.value = ex.iso; }
      section.dataset.actual = ex.actual;
      setMsg("");
    }

    function readEvents() {
      var out = [];
      Array.prototype.forEach.call(el.rows.querySelectorAll("tr"), function (tr) {
        var row = {};
        var ok = true;
        Array.prototype.forEach.call(tr.querySelectorAll("input"), function (input) {
          var v = parseFloat(input.value);
          if (!isFinite(v)) { ok = false; }
          row[input.dataset.key] = v;
        });
        if (ok) { out.push(row); }
      });
      return out;
    }

    /* ---- running it ------------------------------------------------------ */
    function daysFromDate(value) {
      var origin = Date.parse(catalogue.origin);
      var target = Date.parse(value + "T00:00:00Z");
      if (!isFinite(target)) { return null; }
      return (target - origin) / 86400000;
    }

    function classify(m) {
      if (m < 5.0) { return { text: "Below the study threshold", strong: false }; }
      if (m < 6.0) { return { text: "Moderate, 5.0 to 5.9", strong: false }; }
      if (m < 7.0) { return { text: "Strong, 6.0 to 6.9", strong: true }; }
      return { text: "Major, 7.0 and above", strong: true };
    }

    function idle(text) {
      el.readout.innerHTML = "";
      var p = document.createElement("p");
      p.className = "readout__state";
      p.textContent = text;
      el.readout.appendChild(p);
    }

    function run() {
      setMsg("");
      var events = readEvents();
      if (events.length < bundle.min_foreshocks) {
        setMsg("The model needs at least " + bundle.min_foreshocks
          + " complete events in the window. Fill in or remove any partial rows.", true);
        return;
      }
      var lat = parseFloat(el.lat.value), lon = parseFloat(el.lon.value);
      if (!isFinite(lat) || !isFinite(lon)) {
        setMsg("Enter a latitude and longitude for the sequence.", true);
        return;
      }
      /* A recorded sequence carries its own mainshock time; only a custom
         sequence takes the time from the date field. */
      var tEnd;
      if (source() === "recorded") {
        var ex = bundle.examples.filter(function (e) { return e.id === el.pick.value; })[0];
        if (!ex) { setMsg("Pick a recorded sequence.", true); return; }
        lat = ex.epicentre[0];
        lon = ex.epicentre[1];
        tEnd = ex.t_end;
      } else {
        tEnd = daysFromDate(el.when.value);
      }
      if (tEnd === null || !isFinite(tEnd)) {
        setMsg("Enter a valid forecast date.", true);
        return;
      }

      var context = Forecast.regionalContext(catalogue, lat, lon, tEnd, bundle);
      var sorted = events.slice().sort(function (a, b) { return b.before - a.before; });
      var result;
      try {
        result = Forecast.forecast({
          bundle: bundle, model: chosen, events: sorted,
          lat: lat, lon: lon, context: context,
        });
      } catch (err) {
        setMsg("The forecast could not be computed: " + err.message, true);
        return;
      }
      render(result, sorted, context);
    }

    function render(result, events, context) {
      var model = bundle.models[chosen];
      var m = result.magnitude;
      var band = classify(m);
      var actual = source() === "recorded" ? parseFloat(section.dataset.actual) : NaN;

      el.readout.innerHTML = "";
      var frag = document.createDocumentFragment();

      var head = document.createElement("div");
      head.innerHTML = '<span class="readout__mag">' + m.toFixed(2) + "</span>"
        + '<span class="readout__band">Forecast mainshock magnitude. Typical error for '
        + model.label + " is plus or minus " + model.rmse.toFixed(2) + ", so read this as "
        + (m - model.rmse).toFixed(2) + " to " + (m + model.rmse).toFixed(2) + ".</span>";
      var chip = document.createElement("span");
      chip.className = "readout__class" + (band.strong ? " is-strong" : "");
      chip.textContent = band.text;
      head.appendChild(chip);
      frag.appendChild(head);

      var kv = document.createElement("div");
      kv.className = "kv";
      var items = [
        ["Model", model.label],
        ["Skill vs. average", (model.skill > 0 ? "+" : "") + model.skill.toFixed(1) + "%"],
        ["Events in window", String(events.length)],
        ["Largest foreshock", "M " + Math.max.apply(null, events.map(function (e) { return e.mag; })).toFixed(1)],
      ];
      if (result.raw) {
        var bIdx = bundle.features.indexOf("b_mlk");
        var b = result.raw[bIdx];
        items.push(["b-value", isFinite(b) ? b.toFixed(3) : "not estimable"]);
        items.push(["Days since regional M 6.5",
          Math.round(result.raw[bundle.features.indexOf("T_elaps65")]).toLocaleString()]);
      }
      if (isFinite(actual)) {
        items.push(["Observed magnitude", "M " + actual.toFixed(1)]);
        items.push(["Error", (m - actual >= 0 ? "+" : "") + (m - actual).toFixed(2)]);
      }
      items.forEach(function (pair) {
        var cell = document.createElement("div");
        var k = document.createElement("span");
        k.className = "k";
        k.textContent = pair[0];
        var v = document.createElement("span");
        v.className = "v";
        v.textContent = pair[1];
        cell.appendChild(k);
        cell.appendChild(v);
        kv.appendChild(cell);
      });
      frag.appendChild(kv);

      /* Occurrence probability. This answers a different question from the
         magnitude above it: not how large, but whether anything happens at all
         inside the horizon. The machine learning model was built and scored for
         this and beat the historical rate in one cell of nine, so what is shown
         is the rate itself, with the model's measured result stated rather than
         implied. */
      if (bundle.occurrence && bundle.occurrence.cells) {
        frag.appendChild(buildProbability(bundle.occurrence));
      }

      var caution = document.createElement("p");
      caution.className = "caution";
      caution.innerHTML = "<strong>This is a demonstrator, not a warning system.</strong> "
        + "It estimates how large a mainshock would be if one follows this sequence. It says "
        + "nothing about whether one will occur, or when, or where. The typical error is about "
        + "half a magnitude unit, which spans the difference between a tremor and a damaging "
        + "earthquake. Official advisories come from PHIVOLCS.";
      frag.appendChild(caution);

      el.readout.appendChild(frag);
    }

    /* Keep the selected pill in sync without :has(), so the state survives on
       browsers that lack it rather than falling back to unreadable text. */
    function syncSegments() {
      Array.prototype.forEach.call(document.querySelectorAll(".seg label"), function (label) {
        var input = label.querySelector("input");
        label.classList.toggle("is-on", !!(input && input.checked));
      });
    }
    document.addEventListener("change", function (e) {
      if (e.target && e.target.matches && e.target.matches('.seg input')) { syncSegments(); }
    });

    function buildProbability(occ) {
      var wrap = document.createElement("div");
      wrap.className = "prob";

      var head = document.createElement("div");
      head.className = "prob__h";
      head.innerHTML = "<span>Chance something follows, next "
        + occ.horizon_days + " days</span><span>historical rate</span>";
      wrap.appendChild(head);

      var table = document.createElement("table");
      var thead = "<thead><tr><th scope=\"col\">Within</th>";
      occ.thresholds.forEach(function (t) {
        thead += '<th scope="col" style="text-align:right">M ' + t.toFixed(1) + "+</th>";
      });
      thead += "</tr></thead>";

      var body = "<tbody>";
      occ.radii.forEach(function (r) {
        body += "<tr><td>" + r + " km</td>";
        occ.thresholds.forEach(function (t) {
          var cell = occ.cells.filter(function (c) {
            return c.radius === r && Math.abs(c.threshold - t) < 1e-9;
          })[0];
          if (!cell || cell.rate === null) {
            body += '<td style="text-align:right" class="thin">n/a</td>';
          } else if (cell.positives < 25) {
            body += '<td style="text-align:right" class="thin" title="'
              + cell.positives + ' historical cases, too few to quantify">'
              + cell.rate.toFixed(1) + "%*</td>";
          } else {
            body += '<td style="text-align:right" class="v">' + cell.rate.toFixed(1) + "%</td>";
          }
        });
        body += "</tr>";
      });
      body += "</tbody>";
      table.innerHTML = thead + body;
      wrap.appendChild(table);

      var skilful = occ.cells.filter(function (c) {
        return c.verdict && c.verdict.indexOf("beats") !== -1;
      });
      var note = document.createElement("p");
      note.className = "prob__note";
      /* Anchor counts differ per radius, so quote the range rather than one row. */
      var counts = occ.cells.map(function (c) { return c.anchors; });
      var lo = Math.min.apply(null, counts), hi = Math.max.apply(null, counts);
      note.innerHTML = "How often an earthquake of that size actually followed, across "
        + lo.toLocaleString() + " to " + hi.toLocaleString() + " historical occasions "
        + "(depending on radius) when a sequence like this was already under way. "
        + "Not conditioned on your events. A machine learning "
        + "model was trained for this and beat the historical rate in "
        + skilful.length + " of " + occ.cells.length + " cells"
        + (skilful.length
            ? " (M " + skilful[0].threshold.toFixed(1) + "+ within " + skilful[0].radius
              + " km, by " + skilful[0].bss.toFixed(1) + "% Brier skill)"
            : "")
        + ", so the rate is reported instead. Starred values rest on fewer than 25 cases.";
      wrap.appendChild(note);
      return wrap;
    }

    /* ---- wiring ---------------------------------------------------------- */
    Array.prototype.forEach.call(document.querySelectorAll('input[name="source"]'), function (input) {
      input.addEventListener("change", function () {
        var custom = source() === "custom";
        el.customWrap.hidden = !custom;
        el.pickWrap.hidden = custom;
        if (!custom && bundle) {
          var ex = bundle.examples.filter(function (e) { return e.id === el.pick.value; })[0];
          if (ex) { loadExample(ex); }
        }
        setMsg("");
      });
    });
    document.getElementById("addRow").addEventListener("click", function () {
      if (!bundle) { return; }
      addRow(null);
    });
    document.getElementById("run").addEventListener("click", function () {
      if (!bundle) { setMsg("Still loading the models.", false); return; }
      run();
    });

    /* Load when the section comes into view, so the first screen stays light.
       An observer is the cheapest trigger but not a guaranteed one: it needs
       the page to be rendering, and a backgrounded or occluded tab can defer
       the callback indefinitely, which would leave this panel on its loading
       skeleton forever. Touching any control and following a #lab link both
       force the load as well. */
    var started = false;
    function begin() {
      if (started) { return; }
      started = true;
      load();
    }
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) { io.disconnect(); begin(); }
      }, { rootMargin: "400px" });
      io.observe(section);
    }
    section.addEventListener("pointerdown", begin, { once: true });
    section.addEventListener("focusin", begin, { once: true });
    if (window.location.hash === "#lab") { begin(); }
    window.addEventListener("hashchange", function () {
      if (window.location.hash === "#lab") { begin(); }
    });
  })();
