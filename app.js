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


  /* One fetch of the bundle, shared. The forecaster needs it and so do the
     evidence tables further down the page, and it is three megabytes. */
  var _bundle = null;
  function bundlePromise() {
    if (!_bundle) {
      _bundle = fetch("model_bundle.json", { cache: "no-cache" }).then(function (r) {
        if (!r.ok) { throw new Error("model_bundle.json " + r.status); }
        return r.json();
      });
    }
    return _bundle;
  }

  /* =======================================================================
     Forecast lab
     Loads the exported models and the catalogue on demand, recomputes the 27
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
      models: document.getElementById("models"),
      msg: document.getElementById("msg"),
      lat: document.getElementById("lat"),
      lon: document.getElementById("lon"),
      when: document.getElementById("when"),
      upload: document.getElementById("upload"),
      uploadNote: document.getElementById("uploadNote"),
      fault: document.getElementById("faultNote"),
    };
    var bundle = null, catalogue = null, loading = false, chosen = "extra_trees";

    /* Clearing the readout on every failed validation is not cosmetic. A result
       left on screen beside a rejected input reads as the result of that input,
       and an evaluator reported exactly that confusion. Nothing survives a
       refusal to forecast. */
    function setMsg(text, isError) {
      el.msg.textContent = text || "";
      el.msg.className = "msg" + (isError ? " msg--error" : "");
      if (isError) { idle("Fix the highlighted fields, then forecast again."); }
    }

    function clearBad() {
      Array.prototype.forEach.call(section.querySelectorAll(".is-bad"),
        function (node) { node.classList.remove("is-bad"); });
    }

    /* ---- data loading, with real loading and error states ---------------- */
    function load() {
      if (bundle || loading) { return Promise.resolve(); }
      loading = true;
      return Promise.all([
        bundlePromise(),
        fetch("catalogue.json", { cache: "no-cache" }).then(function (r) {
          if (!r.ok) { throw new Error("catalogue.json " + r.status); }
          return r.json();
        }),
      ]).then(function (parts) {
        bundle = parts[0];
        catalogue = parts[1];
        loading = false;
        buildModelChoices();
        syncSegments();
        seedTable();
        idle("Enter a sequence and press Forecast.");
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
        input.addEventListener("change", function () { chosen = key; syncSegments(); });
        el.models.appendChild(label);
      });
      chosen = Object.keys(bundle.models)[0];
    }

    /* ---- the event editor ------------------------------------------------ */
    /* Each foreshock is entered as the moment it happened, not as a decimal
       count of days before the forecast. "5.3523 days before" is a quantity
       nobody reads off a PHIVOLCS bulletin; a date and a time is. The elapsed
       days the features need are computed here instead of by the reader. */
    var COLUMNS = [
      { key: "at", type: "datetime-local", label: "date and time" },
      { key: "mag", type: "number", step: "0.1", min: "1", max: "10", label: "magnitude" },
      { key: "lat", type: "number", step: "0.01", min: "0", max: "25", label: "latitude N" },
      { key: "lon", type: "number", step: "0.01", min: "110", max: "140", label: "longitude E" },
      { key: "depth", type: "number", step: "1", min: "0", max: "750", label: "depth km" },
    ];

    function addRow(values) {
      var tr = document.createElement("tr");
      COLUMNS.forEach(function (col) {
        var td = document.createElement("td");
        var input = document.createElement("input");
        input.type = col.type;
        if (col.step) { input.step = col.step; }
        if (col.min !== undefined) { input.min = col.min; }
        if (col.max !== undefined) { input.max = col.max; }
        input.dataset.key = col.key;
        input.value = values && values[col.key] !== undefined ? values[col.key] : "";
        input.setAttribute("aria-label", col.label);
        input.addEventListener("input", function () { input.classList.remove("is-bad"); });
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
      return tr;
    }

    /* The panel opens on a real sequence from the test partition, shipped in
       the bundle so its epicentre and its foreshocks necessarily agree. The
       dropdown of recorded sequences it replaces could pair the two from
       different places, and in one case put an epicentre 600 km from its own
       foreshocks. */
    function seedTable() {
      var seed = bundle && bundle.seed;
      if (!seed) { addRow(null); addRow(null); addRow(null); return; }
      el.rows.innerHTML = "";
      seed.events.forEach(function (e) { addRow(e); });
      el.lat.value = seed.lat;
      el.lon.value = seed.lon;
      el.when.value = seed.when;
      setMsg("");
      showFault();
    }

    /* ---- validation ------------------------------------------------------
     *
     * Three separate failures used to reach the same forecast. A row with some
     * fields blank was dropped silently, so the model ran on less data than the
     * reader believed they had supplied. A magnitude of 12, or of 0, or a date
     * in the future, was accepted and forecast. And a window whose events were
     * nowhere near each other in space or time was treated as a foreshock
     * sequence because nothing checked that it was one.
     *
     * Every one of those now stops the forecast and says which field is wrong.
     * A refusal is a better answer than a number that cannot mean anything.
     */
    var LIMITS = {
      mag: { lo: 1.0, hi: 10.0, name: "Magnitude",
             note: "The catalogue runs from M 1.3 to M 8.3. No earthquake has "
                 + "ever been recorded above M 9.5." },
      lat: { lo: 0.0, hi: 25.0, name: "Latitude",
             note: "The study region is 0 to 25 degrees north." },
      lon: { lo: 110.0, hi: 140.0, name: "Longitude",
             note: "The study region is 110 to 140 degrees east." },
      depth: { lo: 0.0, hi: 750.0, name: "Depth",
               note: "Hypocentres run from the surface to 750 km." },
    };

    function parseStamp(value) {
      if (!value) { return NaN; }
      /* datetime-local has no zone. The catalogue is in UTC, and reading a
         bulletin time as local would shift every elapsed day by the reader's
         own offset, so the Z is explicit. */
      var iso = value.length === 16 ? value + ":00Z" : value.replace(" ", "T") + "Z";
      return Date.parse(iso);
    }

    function daysFromStamp(ms) {
      var origin = Date.parse(catalogue.origin);
      return (ms - origin) / 86400000;
    }

    function mark(input) {
      if (input) { input.classList.add("is-bad"); }
    }

    /**
     * Read the event table and refuse anything that cannot be a foreshock.
     *
     * Returns {events, errors}. `events` carries `before` in days, computed
     * from each row's own timestamp rather than typed in, and is sorted
     * chronologically whatever order the rows were entered in.
     */
    function readEvents(tEndMs) {
      var events = [], errors = [], seen = {};
      Array.prototype.forEach.call(el.rows.querySelectorAll("tr"), function (tr, i) {
        var inputs = {}, blank = 0, filled = 0;
        Array.prototype.forEach.call(tr.querySelectorAll("input"), function (input) {
          inputs[input.dataset.key] = input;
          if (input.value.trim() === "") { blank += 1; } else { filled += 1; }
        });
        if (filled === 0) { return; }                 // an untouched spare row
        var where = "Row " + (i + 1);
        if (blank > 0) {
          Object.keys(inputs).forEach(function (k) {
            if (inputs[k].value.trim() === "") { mark(inputs[k]); }
          });
          errors.push(where + " is incomplete. Every column is needed: an event "
            + "missing its time or its coordinates cannot be placed in the window.");
          return;
        }

        var ms = parseStamp(inputs.at.value);
        if (!isFinite(ms)) {
          mark(inputs.at);
          errors.push(where + ": the date and time could not be read.");
          return;
        }
        var row = { at: ms };
        var bad = false;
        ["mag", "lat", "lon", "depth"].forEach(function (key) {
          var v = parseFloat(inputs[key].value);
          var lim = LIMITS[key];
          if (!isFinite(v)) {
            mark(inputs[key]);
            errors.push(where + ": " + lim.name.toLowerCase() + " is not a number.");
            bad = true;
            return;
          }
          if (v < lim.lo || v > lim.hi) {
            mark(inputs[key]);
            errors.push(where + ": " + lim.name + " " + v + " is outside "
              + lim.lo + " to " + lim.hi + ". " + lim.note);
            bad = true;
            return;
          }
          row[key] = v;
        });
        if (bad) { return; }

        if (ms >= tEndMs) {
          mark(inputs.at);
          errors.push(where + " is at or after the forecast moment. A foreshock "
            + "precedes the earthquake it is a foreshock of.");
          return;
        }
        var before = (tEndMs - ms) / 86400000;
        if (before > bundle.window_days) {
          mark(inputs.at);
          errors.push(where + " is " + before.toFixed(1) + " days before the forecast "
            + "moment, outside the " + bundle.window_days + "-day observation window "
            + "the models were trained on.");
          return;
        }
        var key = ms + "|" + row.lat.toFixed(2) + "|" + row.lon.toFixed(2);
        if (seen[key]) {
          mark(inputs.at);
          errors.push(where + " repeats the event in row " + seen[key]
            + ": same time, same place. One earthquake counted twice inflates "
            + "the event count and the energy release.");
          return;
        }
        seen[key] = i + 1;
        row.before = before;
        row.input = inputs;
        events.push(row);
      });
      events.sort(function (a, b) { return a.at - b.at; });
      return { events: events, errors: errors };
    }

    /**
     * Do these events look like a foreshock sequence at all?
     *
     * The models were fitted on windows drawn by Maeda's method: events close
     * enough in space and time to belong to one sequence, and all smaller than
     * the earthquake they precede. Nothing stopped a reader entering eight
     * unrelated tremors from opposite ends of the country and receiving a
     * confident number back. These checks apply the same conditions to typed
     * input that the training data had to satisfy.
     *
     * Hirose et al. (2021), Equations 1 and 2: an event of magnitude Mpre
     * draws a window of L km and ta days around itself.
     */
    function maedaWindow(mag) {
      return {
        L: Math.pow(10, 0.5 * mag - 1.8),
        ta: Math.pow(10, (0.17 + 0.85 * (mag - 4.0)) / 1.3) - 0.3,
      };
    }

    function plausibility(events, lat, lon) {
      var errors = [], warnings = [];
      if (events.length < bundle.min_foreshocks) {
        errors.push("At least " + bundle.min_foreshocks + " complete events are needed. "
          + "A b-value cannot be fitted to fewer, and every model in the paper was "
          + "trained on windows holding at least that many.");
        return { errors: errors, warnings: warnings };
      }

      var far = events.filter(function (e) {
        return Forecast.haversineKm(lat, lon, e.lat, e.lon) > bundle.radius_km;
      });
      if (far.length) {
        far.forEach(function (e) { mark(e.input.lat); mark(e.input.lon); });
        errors.push(far.length + (far.length === 1 ? " event lies" : " events lie")
          + " more than " + bundle.radius_km + " km from the epicentre you entered, "
          + "outside the observation window. Either the epicentre is wrong or those "
          + "events belong to a different sequence.");
      }

      /* The largest event in the window sets a floor. A mainshock is by
         definition the largest earthquake of its sequence, which is the rule
         the training set was rebuilt to honour, so a window already holding an
         M 6.5 is not a foreshock sequence for anything the model can forecast. */
      var largest = events.reduce(function (a, e) { return Math.max(a, e.mag); }, -Infinity);
      if (largest >= 7.0) {
        events.forEach(function (e) { if (e.mag === largest) { mark(e.input.mag); } });
        errors.push("The largest event entered is M " + largest.toFixed(1)
          + ". A mainshock is the largest earthquake of its sequence, so this window "
          + "would need a mainshock above M " + largest.toFixed(1) + " — beyond the "
          + "range any of these models can forecast. The training sequences top out "
          + "at M 7.3.");
      }

      /* Maeda's own windows, applied to the sequence the reader typed. Every
         event should fall inside the space-time window of the largest one, or
         they are not one cluster. */
      var anchor = events[events.length - 1];
      var w = maedaWindow(largest);
      var strays = events.filter(function (e) {
        return Forecast.haversineKm(anchor.lat, anchor.lon, e.lat, e.lon) > Math.max(w.L, 25)
          || (anchor.before !== undefined && (e.before - anchor.before) > Math.max(w.ta, 14));
      });
      if (strays.length && !far.length) {
        warnings.push(strays.length + " of the " + events.length + " events sit outside "
          + "Maeda's space-time window for an M " + largest.toFixed(1) + " precursor ("
          + w.L.toFixed(0) + " km, " + w.ta.toFixed(1) + " days). They may belong to a "
          + "different cluster, in which case the features describe two sequences at "
          + "once and the forecast is weaker than its error bar suggests.");
      }

      var span = events[events.length - 1].at - events[0].at;
      if (events.length >= 5 && span < 60000) {
        warnings.push("All " + events.length + " events fall within a minute of each "
          + "other. Repeated reports of one earthquake, relocated, look like this; the "
          + "catalogue collapses pairs within one second and one kilometre, and a "
          + "sequence this tight is worth checking against the bulletin.");
      }
      return { errors: errors, warnings: warnings };
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

    /* The distance from the epicentre to the nearest mapped active fault,
       shown as the reader types rather than only after a forecast. The thesis
       names it as a selected parameter and five of the 27 features summarise
       it, so it belongs beside the coordinates it is computed from. */
    function showFault() {
      if (!el.fault || !bundle) { return; }
      var lat = parseFloat(el.lat.value), lon = parseFloat(el.lon.value);
      if (!isFinite(lat) || !isFinite(lon)) { el.fault.textContent = ""; return; }
      var near = Forecast.nearestSource(lat, lon, bundle.sources);
      if (!isFinite(near.km)) { el.fault.textContent = ""; return; }
      el.fault.innerHTML = "Nearest mapped active fault: <strong>"
        + near.km.toFixed(1) + " km</strong>, at " + near.lat.toFixed(2) + " N "
        + near.lon.toFixed(2) + " E.";
    }

    /* Rewrite the table in chronological order, oldest first, so the reader
       sees the sequence the way the model reads it. Entering events out of
       order is normal when they are copied off a bulletin one at a time, and
       silently reordering them inside the computation while leaving the screen
       scrambled makes the two disagree. */
    function sortTable() {
      var rows = Array.prototype.slice.call(el.rows.querySelectorAll("tr"));
      var keyed = rows.map(function (tr, i) {
        var at = tr.querySelector('input[data-key="at"]');
        var ms = at ? parseStamp(at.value) : NaN;
        return { tr: tr, ms: isFinite(ms) ? ms : Infinity, i: i };
      });
      keyed.sort(function (a, b) { return a.ms - b.ms || a.i - b.i; });
      keyed.forEach(function (k) { el.rows.appendChild(k.tr); });
    }

    function run() {
      clearBad();
      setMsg("");

      var tEndMs = parseStamp(el.when.value);
      if (!isFinite(tEndMs)) {
        mark(el.when);
        setMsg("Enter the date and time you are forecasting from.", true);
        return;
      }
      var newest = catalogue.origin
        ? Date.parse(catalogue.origin) + catalogue.t[catalogue.n - 1] * 86400000 : NaN;
      if (isFinite(newest) && tEndMs > newest + 86400000) {
        mark(el.when);
        setMsg("The forecast moment is after the end of the catalogue ("
          + new Date(newest).toISOString().slice(0, 10) + "). Four of the 27 features "
          + "count days since the last large regional earthquake and are read from "
          + "that record, so there is nothing to read past its end.", true);
        return;
      }

      var lat = parseFloat(el.lat.value), lon = parseFloat(el.lon.value);
      var bad = false;
      [["lat", el.lat, lat], ["lon", el.lon, lon]].forEach(function (pair) {
        var lim = LIMITS[pair[0]];
        if (!isFinite(pair[2]) || pair[2] < lim.lo || pair[2] > lim.hi) {
          mark(pair[1]);
          bad = true;
        }
      });
      if (bad) {
        setMsg("The epicentre must sit inside the study region: 0 to 25 degrees north, "
          + "110 to 140 degrees east.", true);
        return;
      }

      var read = readEvents(tEndMs);
      if (read.errors.length) {
        setMsg(read.errors[0] + (read.errors.length > 1
          ? "  (" + (read.errors.length - 1) + " more problem"
            + (read.errors.length > 2 ? "s" : "") + " marked below.)" : ""), true);
        return;
      }
      sortTable();

      var check = plausibility(read.events, lat, lon);
      if (check.errors.length) {
        setMsg(check.errors[0] + (check.errors.length > 1
          ? "  (" + (check.errors.length - 1) + " more marked below.)" : ""), true);
        return;
      }

      var tEnd = daysFromStamp(tEndMs);
      var events = read.events.map(function (e) {
        return { before: e.before, mag: e.mag, lat: e.lat, lon: e.lon, depth: e.depth };
      });
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

      /* One feature vector per radius, not one shared by all three. Each
         occurrence model was fitted on events inside its own radius, and
         feeding the 50 km model a 100 km window is why those rows used to move
         together even when nothing lay within 50 km. */
      var occByRadius = {};
      ((bundle.occurrence && bundle.occurrence.radii) || []).forEach(function (r) {
        var inside = sorted.filter(function (e) {
          return Forecast.haversineKm(lat, lon, e.lat, e.lon) <= r;
        });
        if (inside.length < bundle.min_foreshocks) { occByRadius[r] = null; return; }
        try {
          var ctx = Forecast.regionalContext(catalogue, lat, lon, tEnd, bundle, r);
          occByRadius[r] = Forecast.buildFeatures(inside, ctx, bundle);
        } catch (err) {
          occByRadius[r] = null;
        }
      });

      if (check.warnings.length) {
        setMsg(check.warnings.join("  "), false);
      }
      render(result, sorted, context, occByRadius, lat, lon);
    }

    /* A magnitude ruler for the readout. The forecast, its error band, the
       largest event that was typed in and, where it is known, what actually
       happened, all on one scale. The question this answers is the one the
       number alone kept provoking: how does the forecast sit against the
       foreshocks it came from. */
    var GAUGE_LO = 4.5, GAUGE_HI = 7.5;

    function gaugePos(v) {
      var c = Math.min(GAUGE_HI, Math.max(GAUGE_LO, v));
      return ((c - GAUGE_LO) / (GAUGE_HI - GAUGE_LO)) * 100;
    }

    function gaugeTick(cls, value) {
      var el = document.createElement("span");
      el.className = "gauge__tick " + cls;
      el.style.left = gaugePos(value).toFixed(2) + "%";
      return el;
    }

    function gaugeKey(cls, label, value) {
      var li = document.createElement("li");
      li.className = cls;
      li.innerHTML = '<span class="gauge__swatch"></span><span class="gauge__label">'
        + label + '</span><span class="gauge__value">' + value + "</span>";
      return li;
    }

    function buildGauge(m, rmse, largest, actual) {
      var wrap = document.createElement("div");
      wrap.className = "gauge";

      var track = document.createElement("div");
      track.className = "gauge__track";

      var band = document.createElement("span");
      band.className = "gauge__band";
      band.style.left = gaugePos(m - rmse).toFixed(2) + "%";
      band.style.width = (gaugePos(m + rmse) - gaugePos(m - rmse)).toFixed(2) + "%";
      track.appendChild(band);

      [5, 6, 7].forEach(function (g) {
        var line = document.createElement("span");
        line.className = "gauge__grid";
        line.style.left = gaugePos(g).toFixed(2) + "%";
        track.appendChild(line);
      });

      track.appendChild(gaugeTick("is-fore", largest));
      if (isFinite(actual)) { track.appendChild(gaugeTick("is-obs", actual)); }
      track.appendChild(gaugeTick("is-now", m));
      wrap.appendChild(track);

      var axis = document.createElement("div");
      axis.className = "gauge__axis";
      [[4.5, "4.5"], [5, "5.0"], [5.5, "5.5"], [6, "6.0"], [6.5, "6.5"], [7, "7.0"], [7.5, "7.5"]].forEach(function (t) {
        var lab = document.createElement("span");
        lab.style.left = gaugePos(t[0]).toFixed(2) + "%";
        lab.textContent = t[1];
        axis.appendChild(lab);
      });
      wrap.appendChild(axis);

      var key = document.createElement("ul");
      key.className = "gauge__key";
      key.appendChild(gaugeKey("is-now", "Forecast, plus or minus "
        + rmse.toFixed(2), m.toFixed(2)));
      key.appendChild(gaugeKey("is-fore", "Largest foreshock entered",
        "M " + largest.toFixed(1)));
      if (isFinite(actual)) {
        key.appendChild(gaugeKey("is-obs", "What actually happened",
          "M " + actual.toFixed(1)));
      }
      wrap.appendChild(key);
      return wrap;
    }

    function render(result, events, context, occByRadius, lat, lon) {
      var model = bundle.models[chosen];
      var m = result.magnitude;
      var band = classify(m);
      var actual = NaN;

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

      var largest = Math.max.apply(null, events.map(function (e) { return e.mag; }));
      var ev = bundle.evidence || {};
      var nSeq = (ev.cleaning && ev.cleaning.length)
        ? ev.cleaning[ev.cleaning.length - 1].n.toLocaleString() : "the";
      /* Read from the measured table, never typed: the page used to quote a
         23.6% improvement that the results had long since replaced with 11.4%,
         and an evaluator caught it. */
      var cover = (ev.spread || []).filter(function (r) {
        return r.model === model.label && r.band.indexOf("All") === 0;
      })[0];
      var hiBand = (ev.spread || []).filter(function (r) {
        return r.model === model.label && r.band.indexOf("7.0") !== -1;
      })[0];

      var kv = document.createElement("div");
      kv.className = "kv";
      var near = Forecast.nearestSource(lat, lon, bundle.sources);
      var items = [
        ["Model", model.label],
        ["Skill vs. average", (model.skill > 0 ? "+" : "") + model.skill.toFixed(1) + "%"],
        ["Events in window", String(events.length)],
        ["Largest foreshock", "M " + largest.toFixed(1)],
      ];
      if (isFinite(near.km)) {
        items.push(["Nearest active fault", near.km.toFixed(1) + " km"]);
      }
      if (result.spread && isFinite(result.spread.hi)) {
        items.push(["Ensemble 90th percentile", "M " + result.spread.hi.toFixed(2)]);
      }
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
      frag.appendChild(buildGauge(m, model.rmse, largest, actual));
      frag.appendChild(kv);

      /* A mainshock is the largest earthquake of its sequence, so a forecast
         under the largest event on screen is the model under-forecasting, not
         a definition being bent. The dataset enforces the rule, the leading
         model respects it on every held-out case, and the weaker ones do not
         always, so say which happened instead of quietly clamping. */
      if (m < largest - 0.005) {
        var gap = document.createElement("p");
        gap.className = "caution";
        gap.innerHTML = "<strong>This forecast is below the largest foreshock, which means the model under-forecast.</strong> "
          + "A mainshock is the largest earthquake of its sequence, so M "
          + largest.toFixed(1) + " is the floor this sequence sets. Every one of the "
          + nSeq + " recorded sequences obeys that rule, each foreshock strictly "
          + "smaller than the mainshock it precedes. Treat M " + largest.toFixed(1)
          + " as the lower bound here.";
        frag.appendChild(gap);
      }

      /* The point forecast is the mean over the ensemble's trees, and a mean
         fitted under squared error shrinks toward the training average. That
         shrinkage is measured in the paper: near zero in the M 5.0 to 5.4 band
         and about one and a half magnitude units above M 7.0. Quoting the
         spread of the trees alongside the mean is the honest way to say so
         without pretending the model can reach a number it cannot. */
      if (result.spread && isFinite(result.spread.hi)) {
        var sp = document.createElement("p");
        sp.className = "prob__note";
        sp.innerHTML = "The " + result.spread.n + " trees in this ensemble forecast "
          + "between M " + result.spread.lo.toFixed(2) + " and M "
          + result.spread.hi.toFixed(2) + " across their middle eighty percent, and "
          + "the headline is their mean. A mean fitted under squared error pulls "
          + "toward the training average, so for a genuinely large sequence the "
          + "ninetieth percentile is the more useful figure."
          + (cover ? " On the test partition it covers the observed magnitude in "
              + cover.covered.toFixed(0) + "% of cases overall" : "")
          + (hiBand ? ", and in " + hiBand.covered.toFixed(0) + "% of the "
              + hiBand.n + " sequences above M 7.0. The model does not reach that "
              + "far, and this page will not claim it does." : ".");
        frag.appendChild(sp);
      }

      /* Occurrence probability. This answers a different question from the
         magnitude above it: not how large, but whether anything happens at all
         inside the horizon. The machine learning model was built and scored for
         this and beat the historical rate in one cell of nine, so what is shown
         is the rate itself, with the model's measured result stated rather than
         implied. */
      var mapPanel = buildMap(events, lat, lon, bundle.occurrence, occByRadius);
      frag.appendChild(mapPanel);

      if (bundle.occurrence && bundle.occurrence.cells) {
        frag.appendChild(buildProbability(bundle.occurrence, occByRadius));
      } else {
        var stale = document.createElement("p");
        stale.className = "prob prob__note";
        stale.textContent = "The occurrence table is missing from the loaded data, "
          + "which means a cached copy is being served. Reload the page to fetch it.";
        frag.appendChild(stale);
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
      /* Now that the map is attached it has a width, so draw it for real. */
      if (mapPanel && typeof mapPanel.redraw === "function") { mapPanel.redraw(); }
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


    /**
     * Locator map for the sequence.
     *
     * There is no tile service here and no map library. The basemap is the
     * catalogue itself: 17,667 epicentres already trace the archipelago and its
     * trenches, and they are the honest backdrop for a seismic forecast because
     * they show exactly where the record has coverage. Drawn on canvas so the
     * 200 km view and the whole-country inset cost one element between them.
     */
    function buildMap(events, lat, lon, occ, occByRadius) {
      var wrap = document.createElement("div");
      wrap.className = "map";

      var head = document.createElement("div");
      head.className = "map__h";
      head.innerHTML = "<span>Where this sequence sits</span><span>"
        + lat.toFixed(2) + " N, " + lon.toFixed(2) + " E</span>";
      wrap.appendChild(head);

      var canvas = document.createElement("canvas");
      wrap.appendChild(canvas);

      var key = document.createElement("div");
      key.className = "map__key";
      key.innerHTML =
        '<span><i style="background:var(--good)"></i>foreshocks you entered</span>'
        + '<span><i style="background:var(--accent)"></i>forecast epicentre</span>'
        + '<span><i style="background:var(--line-2)"></i>catalogued seismicity</span>'
        + '<span><i style="background:var(--fault)"></i>mapped active faults</span>'
        + "<span>rings: 50, 100 and 200 km</span>";
      wrap.appendChild(key);

      function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      }

      function draw() {
        /* A canvas that is not laid out yet, or is in a pane with no width,
           reports zero. Fall back to a usable width so the map draws something
           correct rather than nothing at all. */
        var box = canvas.getBoundingClientRect();
        var W = box.width > 40 ? box.width
              : (wrap.parentNode ? wrap.parentNode.getBoundingClientRect().width : 0);
        if (!(W > 40)) { W = 560; }
        var H = Math.round(Math.min(Math.max(W * 0.72, 260), 420));
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(W * dpr);
        canvas.height = Math.round(H * dpr);
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);

        /* Equirectangular about the epicentre, longitude compressed by cos(lat)
           so a circle of constant ground distance draws as a circle. */
        var halfLat = 2.75;                       // about 305 km, fits the 200 km ring
        var cosLat = Math.cos(lat * Math.PI / 180);
        var scale = (H / 2 - 16) / halfLat;       // pixels per degree of latitude
        function px(la, lo) {
          return [W / 2 + (lo - lon) * cosLat * scale, H / 2 - (la - lat) * scale];
        }

        /* Catalogue backdrop. */
        ctx.fillStyle = token("--line-2");
        ctx.globalAlpha = 0.55;
        for (var i = 0; i < catalogue.n; i++) {
          var dLa = catalogue.lat[i] - lat;
          if (dLa < -halfLat * 1.4 || dLa > halfLat * 1.4) { continue; }
          var q = px(catalogue.lat[i], catalogue.lon[i]);
          if (q[0] < -4 || q[0] > W + 4) { continue; }
          ctx.fillRect(q[0], q[1], 1.4, 1.4);
        }
        ctx.globalAlpha = 1;

        var centre = px(lat, lon);

        /* The mapped active faults the thesis measures every distance against.
           The supplied file is a vertex dump rather than a connected polyline,
           so the export breaks a trace wherever consecutive vertices are more
           than 40 km apart; joining every pair would paint fault strands
           straight across the archipelago. */
        var traces = (bundle.sources && bundle.sources.traces) || [];
        ctx.strokeStyle = token("--fault") || "#3b6ea5";
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.globalAlpha = 0.78;
        traces.forEach(function (trace) {
          var drawn = false;
          ctx.beginPath();
          for (var k = 0; k < trace.length; k++) {
            var dLa = trace[k][0] - lat;
            if (dLa < -halfLat * 1.5 || dLa > halfLat * 1.5) { drawn = false; continue; }
            var q = px(trace[k][0], trace[k][1]);
            if (q[0] < -200 || q[0] > W + 200) { drawn = false; continue; }
            if (drawn) { ctx.lineTo(q[0], q[1]); } else { ctx.moveTo(q[0], q[1]); }
            drawn = true;
          }
          ctx.stroke();
        });
        ctx.globalAlpha = 1;

        /* The distance to the nearest fault, drawn as the leader line the
           authors' evaluator asked to see rather than only stated as a
           number. */
        var near = Forecast.nearestSource(lat, lon, bundle.sources);
        if (isFinite(near.km)) {
          var fp = px(near.lat, near.lon);
          ctx.strokeStyle = token("--fault") || "#3b6ea5";
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(centre[0], centre[1]);
          ctx.lineTo(fp[0], fp[1]);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.arc(fp[0], fp[1], 2.6, 0, Math.PI * 2);
          ctx.fillStyle = token("--fault") || "#3b6ea5";
          ctx.fill();
          /* The label sits at the fault end of the leader, not its midpoint:
             a midpoint lands among the ring labels and buries the 50 km one. */
          var dx = fp[0] - centre[0], dy = fp[1] - centre[1];
          var len = Math.max(Math.hypot(dx, dy), 1);
          var text = near.km.toFixed(1) + " km to fault";
          ctx.font = "10px 'IBM Plex Mono', monospace";
          ctx.textBaseline = "middle";
          ctx.textAlign = dx < 0 ? "left" : "right";
          var pad = 3, tw = ctx.measureText(text).width;
          var lx = fp[0] + (dx / len) * 6, ly = fp[1] + (dy / len) * 6 - 9;
          /* Keep it on the canvas when the fault sits near an edge. */
          var half = ctx.textAlign === "left" ? 0 : tw;
          lx = Math.min(Math.max(lx, half + pad + 2), W - (tw - half) - pad - 2);
          ctx.fillStyle = token("--surface");
          ctx.globalAlpha = 0.88;
          ctx.fillRect(lx - (ctx.textAlign === "left" ? pad : tw + pad), ly - 7,
                       tw + 2 * pad, 14);
          ctx.globalAlpha = 1;
          ctx.fillStyle = token("--fault") || "#3b6ea5";
          ctx.fillText(text, lx, ly);
        }

        /* Radius rings, each labelled with this sequence's probability. A ring
           with no model estimate says so rather than borrowing the figure from
           a wider ring, which is what it used to do. */
        var models = (occ && occ.models) || {};
        [200, 100, 50].forEach(function (km) {
          var rpx = (km / 111.32) * scale;
          ctx.strokeStyle = token("--accent");
          ctx.globalAlpha = 0.34;
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(centre[0], centre[1], rpx, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;

          var label = km + " km";
          var m = models[km + "|5"];
          var rawR = occByRadius ? occByRadius[km] : null;
          if (m && rawR) {
            var pr = Forecast.occurrenceProbability(m, occ.feature_names, rawR);
            if (pr !== null && isFinite(pr)) {
              label += "  " + (100 * pr).toFixed(0) + "%";
            }
          } else if (occByRadius && Object.prototype.hasOwnProperty.call(occByRadius, km)) {
            label += "  no events";
          }
          /* Below each ring, not above it. The whole-country inset occupies the
             top right and the fault leader usually runs up or sideways, so the
             space under the ring is the one reliably free of both. An opaque
             backing keeps the label legible where it crosses the catalogue
             backdrop. */
          ctx.font = "10px 'IBM Plex Mono', monospace";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          var ly = centre[1] + rpx + 9;
          if (ly > H - 6) { ly = centre[1] - rpx - 9; }
          var tw = ctx.measureText(label).width;
          ctx.fillStyle = token("--surface");
          ctx.globalAlpha = 0.85;
          ctx.fillRect(centre[0] - tw / 2 - 3, ly - 7, tw + 6, 14);
          ctx.globalAlpha = 1;
          ctx.fillStyle = token("--mute");
          ctx.fillText(label, centre[0], ly);
        });

        /* Foreshocks, sized by magnitude. */
        events.forEach(function (e) {
          var q = px(e.lat, e.lon);
          var rad = 2.6 + Math.max(e.mag - 3.5, 0) * 1.5;
          ctx.fillStyle = token("--good");
          ctx.globalAlpha = 0.85;
          ctx.beginPath();
          ctx.arc(q[0], q[1], rad, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        });

        /* Forecast epicentre. */
        ctx.fillStyle = token("--accent");
        ctx.beginPath();
        ctx.arc(centre[0], centre[1], 5.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = token("--surface");
        ctx.lineWidth = 1.6;
        ctx.stroke();

        /* Whole-country inset, so the reader can place the view at a glance. */
        var iw = 74, ih = 96, ix = W - iw - 12, iy = 12;
        ctx.fillStyle = token("--surface");
        ctx.strokeStyle = token("--line-2");
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.rect(ix, iy, iw, ih);
        ctx.fill();
        ctx.stroke();
        var LA0 = 4, LA1 = 21, LO0 = 116, LO1 = 128;
        function ipx(la, lo) {
          return [ix + ((lo - LO0) / (LO1 - LO0)) * iw,
                  iy + ih - ((la - LA0) / (LA1 - LA0)) * ih];
        }
        ctx.fillStyle = token("--line-2");
        for (var j = 0; j < catalogue.n; j += 3) {
          var s2 = ipx(catalogue.lat[j], catalogue.lon[j]);
          ctx.fillRect(s2[0], s2[1], 0.7, 0.7);
        }
        var here = ipx(lat, lon);
        ctx.fillStyle = token("--accent");
        ctx.beginPath();
        ctx.arc(here[0], here[1], 3, 0, Math.PI * 2);
        ctx.fill();
      }

      /* The canvas has no width until it is in the document, and a frame
         callback never arrives in a pane that is not compositing, so the
         caller redraws once the node is attached and this is only a backstop. */
      wrap.redraw = draw;
      if (typeof requestAnimationFrame === "function") { requestAnimationFrame(draw); }
      var scheme = window.matchMedia("(prefers-color-scheme: dark)");
      if (scheme.addEventListener) { scheme.addEventListener("change", draw); }
      var resizeTimer = null;
      window.addEventListener("resize", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(draw, 150);
      });
      return wrap;
    }

    function buildProbability(occ, occByRadius) {
      var wrap = document.createElement("div");
      wrap.className = "prob";

      var models = occ.models || {};
      var anyModel = occByRadius && Object.keys(models).length > 0
        && occ.radii.some(function (r) { return occByRadius[r]; });
      var thinRadii = (occ.radii || []).filter(function (r) {
        return occByRadius && !occByRadius[r];
      });

      var head = document.createElement("div");
      head.className = "prob__h";
      head.innerHTML = "<span>Chance something follows, next " + occ.horizon_days
        + " days</span><span>" + (anyModel ? "for this sequence" : "historical rate")
        + "</span>";
      wrap.appendChild(head);

      var table = document.createElement("table");
      var conf = occ.confidence || 95;
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
          } else {
            /* Quote the year-block interval where it exists. It drops the
               independence assumption Wilson needs and is the wider, more
               defensible of the two. */
            var ci = cell.block_ci && cell.block_ci !== "—" ? cell.block_ci : cell.ci;
            var moe = (cell.block_moe !== null && cell.block_moe !== undefined)
              ? cell.block_moe : cell.moe;
            var thin = cell.positives < 25;
            var model = models[r + "|" + t];
            /* One feature vector per radius. Feeding the 50 km model a window
               computed at 100 km made all three rows move together even when
               nothing the reader entered lay within 50 km of the epicentre. */
            var rawR = occByRadius ? occByRadius[r] : null;
            var fitted = (rawR && model)
              ? Forecast.occurrenceProbability(model, occ.feature_names, rawR) : null;

            if (fitted !== null && fitted !== undefined && isFinite(fitted)) {
              /* A model earned its place in this cell, so the headline is its
                 estimate for the events on screen and the historical rate sits
                 underneath as the reference it has to beat. */
              body += '<td style="text-align:right" class="v"'
                + ' title="Model estimate for this sequence. Historical rate '
                + cell.rate.toFixed(1) + "%, " + conf + "% CI " + ci + "%. "
                + "Brier skill " + cell.bss.toFixed(1) + '% over that rate.">'
                + (100 * fitted).toFixed(1) + "%"
                + '<span class="moe">base ' + cell.rate.toFixed(1) + "%</span>"
                + "</td>";
            } else {
              body += '<td style="text-align:right" class="' + (thin ? "thin" : "v") + '"'
                + ' title="Historical rate. ' + cell.positives + " of " + cell.anchors
                + " occasions" + (ci ? ", " + conf + "% CI " + ci + "%" : "")
                + ". No model beat this rate, so the rate is shown." + '">'
                + cell.rate.toFixed(1) + "%" + (thin ? "*" : "")
                + (moe !== null && moe !== undefined
                    ? '<span class="moe">&plusmn;' + moe.toFixed(1) + "</span>"
                    : "")
                + "</td>";
            }
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
      if (anyModel) {
        note.innerHTML = "The M 5.0 column is a model estimate for the events you entered, "
          + "so it moves as you add or remove foreshocks; the smaller figure beneath is the "
          + "historical rate it has to beat. That model is a regularised logistic regression "
          + "over eight features and beats the rate by 2 to 6% Brier skill depending on "
          + "radius. No model beat the rate for M 6.0 or above, so those columns show the "
          + "historical frequency with its margin of error at " + conf + "% confidence, from "
          + "a bootstrap resampling whole years rather than individual anchors. Hover any "
          + "cell for the detail. Starred values rest on fewer than 25 historical cases."
          + (thinRadii.length
              ? " The " + thinRadii.join(" and ") + " km row" + (thinRadii.length > 1
                  ? "s hold" : " holds") + " fewer than " + bundle.min_foreshocks
                + " of your events, so " + (thinRadii.length > 1 ? "they fall" : "it falls")
                + " back to the historical rate: each radius is a separately trained "
                + "model and none of them may be fed a window it was not trained on."
              : "");
        wrap.appendChild(note);
        return wrap;
      }
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
        + ", so the rate is reported instead. Each figure carries its margin of error in "
        + "percentage points at " + conf + "% confidence, from a bootstrap that resamples "
        + "whole years rather than individual anchors, because overlapping windows from one "
        + "catalogue are not independent trials. Hover a cell for the interval. Starred "
        + "values rest on fewer than 25 historical cases and should be read as an order of "
        + "magnitude, not a number.";
      wrap.appendChild(note);
      return wrap;
    }

    /* ---- reading a sequence out of a spreadsheet -------------------------
     *
     * Typing eight events by hand to check one sequence is the kind of work
     * that makes a reader stop checking. A .csv is parsed here; a .xlsx is a
     * zip of XML and parsing one would mean shipping a library, so the panel
     * says what it accepts instead of failing silently on the wrong file.
     *
     * Column names are matched loosely, because a bulletin exported from Excel
     * will not use these exact words. Nothing is guessed about which column is
     * which: if a required one is missing the import is refused and names the
     * one it could not find.
     */
    var FIELD_ALIASES = {
      at: ["date and time", "date time", "datetime", "origin time", "date - time",
           "date and time parameter", "when", "time", "date"],
      mag: ["magnitude", "mag", "m", "magnitude parameter", "mw", "ms", "mb", "ml"],
      lat: ["latitude", "lat", "lat n", "latitude n", "lat (n)"],
      lon: ["longitude", "lon", "long", "lon e", "longitude e", "long (e)"],
      depth: ["depth", "depth km", "depth (km)", "depth parameter"],
    };

    function splitCsvLine(line) {
      var out = [], cur = "", quoted = false;
      for (var i = 0; i < line.length; i++) {
        var ch = line[i];
        if (quoted) {
          if (ch === '"' && line[i + 1] === '"') { cur += '"'; i += 1; }
          else if (ch === '"') { quoted = false; }
          else { cur += ch; }
        } else if (ch === '"') { quoted = true; }
        else if (ch === "," || ch === "\t" || ch === ";") { out.push(cur); cur = ""; }
        else { cur += ch; }
      }
      out.push(cur);
      return out.map(function (v) { return v.trim(); });
    }

    /* Headers come off a bulletin, not out of a schema, so "Date - Time",
       "Date and Time Parameter" and "origin_time" all have to land on the same
       field. Comparison is on letters and digits alone, which collapses the
       punctuation and spacing a spreadsheet export invents. */
    function squash(text) {
      return String(text).toLowerCase().replace(/[^a-z0-9]+/g, "");
    }

    function matchColumns(header) {
      var keys = header.map(squash);
      var map = {}, taken = {};
      function claim(key, at) {
        if (at === -1 || taken[at]) { return false; }
        map[key] = at;
        taken[at] = true;
        return true;
      }
      /* Exact matches first, across every field, so a header that names one
         field exactly is never stolen by another field's prefix rule. */
      Object.keys(FIELD_ALIASES).forEach(function (key) {
        FIELD_ALIASES[key].some(function (alias) {
          return claim(key, keys.indexOf(squash(alias)));
        });
      });
      Object.keys(FIELD_ALIASES).forEach(function (key) {
        if (map[key] !== undefined) { return; }
        FIELD_ALIASES[key].some(function (alias) {
          var want = squash(alias);
          var at = -1;
          for (var i = 0; i < keys.length; i++) {
            if (keys[i].indexOf(want) !== -1 && !taken[i]) { at = i; break; }
          }
          return claim(key, at);
        });
      });
      return map;
    }

    function normaliseStamp(value) {
      var v = String(value).trim();
      if (!v) { return ""; }
      /* "2021-08-27 10:22:23" and "2021-08-27T10:22" both become the value a
         datetime-local input accepts; anything else is handed back unchanged
         so the row fails validation visibly rather than being dropped. */
      var m = v.match(/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})[ T]+(\d{1,2}):(\d{2})/);
      if (m) {
        var pad = function (x) { return String(x).length < 2 ? "0" + x : String(x); };
        return m[1] + "-" + pad(m[2]) + "-" + pad(m[3]) + "T" + pad(m[4]) + ":" + m[5];
      }
      var d = Date.parse(v.indexOf("T") === -1 ? v.replace(" ", "T") : v);
      return isFinite(d) ? new Date(d).toISOString().slice(0, 16) : v;
    }

    function importCsv(text) {
      var lines = text.split(/\r?\n/).filter(function (l) { return l.trim() !== ""; });
      if (lines.length < 2) {
        return { error: "The file has no data rows under its header." };
      }
      var header = splitCsvLine(lines[0]);
      var map = matchColumns(header);
      var missing = ["at", "mag", "lat", "lon", "depth"].filter(function (k) {
        return map[k] === undefined;
      });
      if (missing.length) {
        return { error: "Could not find a column for " + missing.join(", ")
          + ". The header read: " + header.join(", ") + "." };
      }
      var rows = [];
      for (var i = 1; i < lines.length; i++) {
        var cells = splitCsvLine(lines[i]);
        rows.push({
          at: normaliseStamp(cells[map.at]),
          mag: cells[map.mag], lat: cells[map.lat],
          lon: cells[map.lon], depth: cells[map.depth],
        });
      }
      return { rows: rows };
    }

    function handleUpload(file) {
      if (!file) { return; }
      if (/\.xlsx?$/i.test(file.name)) {
        el.uploadNote.textContent = "An .xlsx file is a zipped XML workbook and this "
          + "page carries no library to open one. Save it as CSV from Excel "
          + "(File, Save As, CSV UTF-8) and upload that.";
        el.uploadNote.className = "help msg--error";
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        var parsed = importCsv(String(reader.result));
        if (parsed.error) {
          el.uploadNote.textContent = parsed.error;
          el.uploadNote.className = "help msg--error";
          return;
        }
        el.rows.innerHTML = "";
        parsed.rows.forEach(function (r) { addRow(r); });
        sortTable();
        el.uploadNote.textContent = parsed.rows.length + " row"
          + (parsed.rows.length === 1 ? "" : "s") + " read from " + file.name
          + ". Check the epicentre and the forecast moment above, then press Forecast; "
          + "every row is validated the same way a typed one is.";
        el.uploadNote.className = "help";
        setMsg("");
      };
      reader.onerror = function () {
        el.uploadNote.textContent = "The file could not be read.";
        el.uploadNote.className = "help msg--error";
      };
      reader.readAsText(file);
    }

    /* ---- wiring ---------------------------------------------------------- */
    document.getElementById("addRow").addEventListener("click", function () {
      if (!bundle) { return; }
      addRow(null);
    });
    document.getElementById("run").addEventListener("click", function () {
      if (!bundle) { setMsg("Still loading the models.", false); return; }
      run();
    });
    var sortBtn = document.getElementById("sortRows");
    if (sortBtn) {
      sortBtn.addEventListener("click", function () {
        sortTable();
        setMsg("Events reordered oldest first.", false);
      });
    }
    if (el.upload) {
      el.upload.addEventListener("change", function () {
        handleUpload(el.upload.files && el.upload.files[0]);
      });
    }
    [el.lat, el.lon].forEach(function (input) {
      if (input) { input.addEventListener("input", showFault); }
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

  /* =======================================================================
     Evidence panels.

     Every figure on this page used to be typed into the markup by hand, and
     when the data set changed the prose went on quoting the old one. A thesis
     evaluator caught exactly that: the copy claimed a 23.6% improvement while
     the results table said 11.4%. These panels are filled at run time from the
     same bundle the forecaster uses, which is written by the pipeline from its
     own output tables, so a number can only be wrong here if it is wrong
     everywhere.
     ======================================================================= */
  (function () {
    var targets = ["evidenceCleaning", "evidenceWindows", "evidenceScales",
                   "evidenceFeatures", "evidenceMetrics", "evidenceBands",
                   "evidenceSupport", "evidenceCase"];
    if (!targets.some(function (id) { return document.getElementById(id); })) { return; }

    function el(id) { return document.getElementById(id); }

    function rows(target, data, build) {
      var node = el(target);
      if (!node || !data || !data.length) { return; }
      node.innerHTML = "";
      data.forEach(function (d, i) {
        var tr = document.createElement("tr");
        tr.innerHTML = build(d, i);
        node.appendChild(tr);
      });
    }

    function num(v, dp) {
      return (v === null || v === undefined || !isFinite(v)) ? "" : v.toFixed(dp);
    }

    function paint(ev) {
      /* --- the cleaning funnel, as proportional bars --------------------- */
      var funnel = el("evidenceCleaning");
      if (funnel && ev.cleaning && ev.cleaning.length) {
        /* Square-root widths, like the figure: the last stage is a hundredth
           of the first and a linear bar for it would be invisible. The count
           is printed on every row, so the bar is an aid and not the number. */
        var widest = Math.sqrt(ev.cleaning[0].n);
        funnel.innerHTML = "";
        ev.cleaning.forEach(function (stage, i) {
          var row = document.createElement("div");
          row.className = "funnel__row" + (i === ev.cleaning.length - 1 ? " is-final" : "");
          row.innerHTML = '<span class="funnel__label">' + stage.label + "</span>"
            + '<span class="funnel__bar"><i style="width:'
            + (100 * Math.sqrt(stage.n) / widest).toFixed(2) + '%"></i>'
            + '<b>' + stage.n.toLocaleString() + "</b></span>"
            + '<span class="funnel__note">' + (stage.note || "") + "</span>";
          funnel.appendChild(row);
        });
      }

      rows("evidenceWindows", ev.maeda_windows, function (w) {
        return "<td>M " + w.mpre.toFixed(1) + "</td><td>" + w.l_km.toFixed(1)
          + "</td><td>" + w.ta_days.toFixed(1) + "</td><td>M "
          + w.cutoff.toFixed(1) + "</td>";
      });

      rows("evidenceScales", ev.scales, function (s) {
        /* The full description lives in the prose beside this table; the
           column is too narrow to hold a sentence without wrapping to four
           lines and crowding the counts out. */
        return "<td>" + s.rank + '</td><td title="' + s.measures + '"><strong>'
          + s.scale + "</strong>" + '<span class="moe">' + (s.short || "")
          + '</span></td><td style="text-align:right">' + s.reported.toLocaleString()
          + '</td><td style="text-align:right">' + s.adopted.toLocaleString()
          + '<span class="moe">' + s.pct.toFixed(1) + "%</span></td>";
      });

      /* --- the 27 features, with how much each one actually moves a forecast */
      if (ev.features) {
        var weight = {};
        (ev.shap || []).forEach(function (r) { weight[r.feature] = r.mean_abs; });
        rows("evidenceFeatures", ev.features, function (f) {
          var w = weight[f.name];
          return "<td><code>" + f.name + "</code></td><td class=\"thin\">"
            + (f.category || "") + "</td><td>" + (f.description || "")
            + '</td><td style="text-align:right" class="' + (w ? "v" : "thin") + '">'
            + (w ? w.toFixed(3) : "&mdash;") + "</td>";
        });
      }

      rows("evidenceMetrics", ev.leaderboard, function (m) {
        var skill = (m.skill > 0 ? "+" : "") + m.skill.toFixed(1) + "%";
        return "<td>" + m.model
          + (m.baseline ? " <span class=\"thin\">reference, not a model</span>" : "")
          + '</td><td style="text-align:right">' + m.rmse.toFixed(3)
          + '</td><td style="text-align:right">' + m.mse.toFixed(3)
          + '</td><td style="text-align:right">' + m.mae.toFixed(3)
          + '</td><td style="text-align:right">' + m.r2.toFixed(3)
          + '</td><td style="text-align:right" class="thin">' + m.ci
          + '</td><td style="text-align:right" class="' + (m.skill > 0 ? "accent" : "")
          + '">' + (m.baseline ? "0.0%" : skill) + "</td>";
      });
      /* The class belongs on the row, which innerHTML on a <tr> cannot set. */
      var metrics = el("evidenceMetrics");
      if (metrics && ev.leaderboard) {
        Array.prototype.forEach.call(metrics.querySelectorAll("tr"), function (tr, i) {
          var m = ev.leaderboard[i];
          if (!m) { return; }
          tr.className = m.baseline ? "is-ref" : (i === 0 ? "is-top" : "");
        });
      }

      var lead = (ev.bands || []).filter(function (b) { return b.model === "Extra Trees"; });
      rows("evidenceBands", lead, function (b) {
        return "<td>" + b.band + '</td><td style="text-align:right">' + b.n
          + '</td><td style="text-align:right">M ' + b.forecast.toFixed(2)
          + '</td><td style="text-align:right" class="' + (b.bias < -0.3 ? "accent" : "")
          + '">' + (b.bias > 0 ? "+" : "") + b.bias.toFixed(2) + "</td>";
      });

      rows("evidenceSupport", ev.support, function (sup) {
        return "<td>" + sup.band + '</td><td style="text-align:right">' + sup.train
          + '</td><td style="text-align:right">' + sup.val
          + '</td><td style="text-align:right">' + sup.test + "</td>";
      });

      var block = (ev.shap_cases || [])[0];
      if (block) {
        var caption = el("evidenceCase") && el("evidenceCase").closest("table");
        if (caption && caption.querySelector("caption")) {
          caption.querySelector("caption").textContent =
            block.title.replace(/^Case \d+: /, "How one forecast was built. ");
        }
        rows("evidenceCase", block.rows, function (r) {
          var sign = r.shap > 0 ? "+" : "";
          return "<td>" + (r.value === null ? r.feature
                  : "<code>" + r.feature + "</code> = " + r.value)
            + '</td><td style="text-align:right" class="'
            + (Math.abs(r.shap) > 0.05 ? "v" : "thin") + '">'
            + (r.feature.indexOf("Base value") === 0 ? "" : sign + r.shap.toFixed(3))
            + '</td><td style="text-align:right">' + r.running.toFixed(2) + "</td>";
        });
      }
    }

    /* Shares the forecaster's fetch rather than pulling three megabytes twice. */
    bundlePromise().then(function (b) {
      if (b && b.evidence) { paint(b.evidence); }
    }).catch(function () { /* the markup already says what each table holds */ });
  })();
