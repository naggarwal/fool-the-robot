/* Fool the Robot — frontend controller.
 * Consumes server->client "result" messages over /ws, renders the primary
 * guess, confidence bars, and the (separate) familiarity meter. Sends
 * {"type":"tune", <field>:value} on slider input. Auto-reconnects. */

(function () {
  "use strict";

  // ---- Band presentation ------------------------------------------------
  const BANDS = {
    confident: { color: "#2ee06a", glow: "#2ee06a55", caption: "Pretty sure!" },
    hedging:   { color: "#ffc23d", glow: "#ffc23d55", caption: "Hmm, not certain…" },
    confused:  { color: "#ff6a3d", glow: "#ff6a3d55", caption: "Wait… I'm confused!" },
    unknown:   { color: "#b57bff", glow: "#b57bff55", caption: "I've never seen that before!" },
    idle:      { color: "#4a566b", glow: "#4a566b55", caption: "" },
  };

  // ---- Elements ---------------------------------------------------------
  const el = {
    guess:    document.getElementById("guess"),
    primary:  document.getElementById("primary"),
    caption:  document.getElementById("caption"),
    bars:     document.getElementById("bars"),
    idle:     document.getElementById("idle"),
    conn:     document.getElementById("conn"),
    famFill:  document.getElementById("fam-fill"),
    famNeedle:document.getElementById("fam-needle"),
    famWord:  document.getElementById("fam-word"),
    rawLabel: document.getElementById("raw-label"),
    rawSim:   document.getElementById("raw-sim"),
    face:     document.getElementById("face"),
    arm:      document.getElementById("arm"),
    armBtn:   document.getElementById("arm-toggle"),
    root:     document.documentElement,
  };

  // ---- Confidence bars --------------------------------------------------
  // Keep up to 5 stable rows keyed by slot index so widths animate rather
  // than teleport when labels reshuffle.
  const MAX_BARS = 5;
  const rows = [];
  for (let i = 0; i < MAX_BARS; i++) {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML =
      '<span class="bar-label"></span>' +
      '<span class="bar-pct"></span>' +
      '<span class="bar-track"><span class="bar-fill"></span></span>';
    el.bars.appendChild(row);
    rows.push({
      row,
      label: row.querySelector(".bar-label"),
      pct:   row.querySelector(".bar-pct"),
      fill:  row.querySelector(".bar-fill"),
    });
  }

  function renderBars(top5) {
    for (let i = 0; i < MAX_BARS; i++) {
      const r = rows[i];
      const d = top5 && top5[i];
      if (d) {
        r.row.style.display = "";
        r.row.classList.toggle("lead", i === 0);
        r.label.textContent = d.label;
        r.pct.textContent = Math.round(d.pct) + "%";
        r.fill.style.width = Math.max(0, Math.min(100, d.pct)) + "%";
      } else {
        r.row.style.display = "none";
      }
    }
  }

  // ---- Familiarity meter (independent of the bars) ----------------------
  function famColor(v) {
    if (v >= 60) return "#2ee06a";   // HIGH  — green
    if (v <= 35) return "#ff5d5d";   // LOW   — red
    return "#ffc23d";                // MED   — amber
  }
  function famWord(v) {
    if (v >= 60) return "HIGH";
    if (v <= 35) return "LOW";
    return "MEDIUM";
  }
  function renderFamiliarity(v) {
    v = Math.max(0, Math.min(100, Number(v) || 0));
    const color = famColor(v);
    // Arc fill: pathLength is 100, so dasharray "<v> <100-v>" fills v%.
    el.famFill.style.strokeDasharray = v + " " + (100 - v);
    el.famFill.style.stroke = color;
    // Needle sweeps a 180° arc: 0 -> points left, 100 -> points right.
    const deg = (v / 100) * 180 - 90;
    el.famNeedle.style.transform = "rotate(" + deg + "deg)";
    el.famNeedle.style.stroke = color;
    el.root.style.setProperty("--fam-color", color);
    el.famWord.textContent = famWord(v);
  }

  // ---- Apply a full result ---------------------------------------------
  const FACE_EXPRESSIONS = ["idle", "confident", "hedging", "confused", "unknown", "down"];
  function setFace(expression) {
    if (!el.face) return;
    FACE_EXPRESSIONS.forEach(function (e) {
      el.face.classList.toggle("exp-" + e, e === expression);
    });
  }

  function applyBand(band) {
    const b = BANDS[band] || BANDS.idle;
    el.root.style.setProperty("--band", b.color);
    el.root.style.setProperty("--band-glow", b.glow);
    el.caption.textContent = b.caption;
    // Face is driven from the SAME band as the caption and bars, so the
    // expression can never contradict the numbers next to it.
    setFace(FACE_EXPRESSIONS.indexOf(band) !== -1 ? band : "idle");
  }

  function showIdle(isIdle) {
    el.idle.classList.toggle("hidden", !isIdle);
  }

  // ---- Arm gate ---------------------------------------------------------
  // Local state is INTENT only; `msg.armed` from the server is what gets
  // rendered. sticky = the ON/OFF toggle, holding = spacebar is down.
  let sticky = true;      // matches the server's ship-armed default
  let holding = false;
  let holdTimer = null;
  const HOLD_KEEPALIVE_MS = 500;   // server drops a hold after 1.5s of silence

  function sendArm(armed, hold) {
    const sock = window.__foolbotWS;
    if (!sock || sock.readyState !== WebSocket.OPEN) return;
    sock.send(JSON.stringify({ type: "arm", armed: armed, hold: !!hold }));
  }

  function setSticky(on) {
    sticky = !!on;
    if (sticky) stopHold();          // no point peeking at an already-open eye
    sendArm(sticky, false);
    renderArmButton();
  }

  function startHold() {
    if (holding || sticky) return;   // spacebar is a no-op while sticky-ON
    holding = true;
    sendArm(true, true);
    // Repeat while held: the server closes the gate on its own if these stop,
    // so a closed tab or a wedged key cannot leave the booth armed all day.
    holdTimer = setInterval(function () { sendArm(true, true); }, HOLD_KEEPALIVE_MS);
  }

  function stopHold() {
    if (holdTimer) { clearInterval(holdTimer); holdTimer = null; }
    if (!holding) return;
    holding = false;
    sendArm(false, true);
  }

  function renderArmButton() {
    if (!el.armBtn) return;
    el.armBtn.textContent = sticky ? "Turn robot OFF" : "Turn robot ON";
    el.armBtn.classList.toggle("is-off", !sticky);
  }

  function renderArmChip(armed) {
    if (!el.arm) return;
    el.arm.textContent = armed ? "● watching" : "off";
    el.arm.className = "arm " + (armed ? "arm--on" : "arm--off");
  }

  function wireArmControls() {
    renderArmButton();
    if (el.armBtn) {
      el.armBtn.addEventListener("click", function () { setSticky(!sticky); });
      // Otherwise SPACE would re-click the focused button instead of peeking.
      el.armBtn.addEventListener("keydown", function (e) {
        if (e.code === "Space" || e.key === " ") e.preventDefault();
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.code === "Space" || e.key === " ") {
        // Space otherwise scrolls the panel and nudges whichever tuning slider
        // the operator touched last.
        e.preventDefault();
        if (e.repeat) return;        // auto-repeat would flood the socket
        startHold();
      } else if (e.key === "o" || e.key === "O") {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.repeat) return;   // a leaned-on key must not strobe the booth
        setSticky(!sticky);
      }
    });
    document.addEventListener("keyup", function (e) {
      if (e.code === "Space" || e.key === " ") stopHold();
    });
    // keyup never arrives if focus leaves mid-hold (cmd-tab, screensaver,
    // someone clicking the desktop) -- without these the booth sticks ON.
    window.addEventListener("blur", stopHold);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stopHold();
    });
  }

  function handleResult(msg) {
    // Live operator readout (always update if provided).
    if (msg.raw_top_label != null) el.rawLabel.textContent = msg.raw_top_label;
    if (msg.raw_top_sim != null)   el.rawSim.textContent = Number(msg.raw_top_sim).toFixed(3);

    syncSliders(msg);   // sliders must show what the SERVER is actually running

    // Random-guess mode must be impossible to mistake for the real thing.
    const banner = document.getElementById("stub-banner");
    if (banner) banner.classList.toggle("hidden", !msg.stub);

    // The gate outranks presence: a disarmed booth must read as resting even
    // with an object sitting in the zone.
    if (msg.armed === false) {
      renderArmChip(false);
      setIdleCopy("off");
      showIdle(true);
      applyBand("idle");     // idle face, NOT the "down" face -- off ≠ broken
      renderBars([]);
      // Nothing is being classified, so the operator readout must not keep
      // displaying the last object as though it were current.
      el.rawLabel.textContent = "—";
      el.rawSim.textContent = "—";
      return;
    }
    renderArmChip(true);
    setIdleCopy("idle");

    if (msg.present === false) {
      showIdle(true);
      applyBand("idle");
      return;
    }
    showIdle(false);

    const top5 = msg.top5 || [];
    el.primary.textContent = top5.length ? top5[0].label : "—";
    applyBand(msg.band);           // band is authoritative from server
    renderBars(top5);
    renderFamiliarity(msg.familiarity);
  }

  // ---- WebSocket with auto-reconnect -----------------------------------
  let ws = null;
  let reconnectDelay = 500;
  const MAX_DELAY = 5000;

  // "Nothing in the zone" and "the server went away" used to render as the
  // identical "Show me something!" screen. A volunteer holding an object at a
  // dead booth would see the same thing as a working idle one -- and it already
  // cost a wrong diagnosis once during calibration. Make the two distinct.
  // "off" is a THIRD state, deliberately not folded into either of the other
  // two: a resting booth is neither waiting for an object nor broken, and a
  // child holding something up to a robot that says "Show me something!" would
  // read the silence as a bug.
  const IDLE_COPY = {
    idle: ["👀", "Show me something!", "Hold an object up to the camera."],
    down: ["😴", "Waking up…", "Reconnecting to the robot's brain."],
    off:  ["✋", "Robot is resting", "Hold SPACE to wake it up for a look."],
  };
  function setIdleCopy(kind) {
    const [emoji, text, sub] = IDLE_COPY[kind];
    const e = document.getElementById("idle-emoji");
    const t = document.getElementById("idle-text");
    const s = document.getElementById("idle-sub");
    if (e) e.textContent = emoji;
    if (t) t.textContent = text;
    if (s) s.textContent = sub;
  }

  function setConn(up) {
    el.conn.textContent = up ? "● live" : "reconnecting…";
    el.conn.className = "conn " + (up ? "conn--up" : "conn--down");
    // While the socket is down the panel must NOT claim to be waiting for an
    // object -- it is not receiving anything at all.
    if (!up) {
      setIdleCopy("down");
      showIdle(true);
      applyBand("idle");
      setFace("down");   // must not look like a booth patiently waiting
      // A hold cannot survive the socket that was carrying it, and the chip
      // must not keep asserting a gate state nobody is reporting.
      stopHold();
      if (el.arm) { el.arm.textContent = "—"; el.arm.className = "arm arm--down"; }
    }
    // Deliberately no setIdleCopy() on the up branch: handleResult owns the
    // copy and sets it on every frame. Guessing "idle" here would flash "Show
    // me something!" at a booth that reconnected while switched off.
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws";
    try {
      ws = new WebSocket(url);
    } catch (e) {
      scheduleReconnect();
      return;
    }
    window.__foolbotWS = ws; // expose for send() below

    ws.onopen = function () {
      setConn(true);
      reconnectDelay = 500;
      // Re-assert the toggle after a reconnect (or a server restart), or the
      // button could read OFF against a freshly-armed engine.
      sendArm(sticky, false);
    };
    ws.onmessage = function (ev) {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg && msg.type === "result") handleResult(msg);
    };
    ws.onclose = function () { setConn(false); scheduleReconnect(); };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }

  function scheduleReconnect() {
    setConn(false);
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(MAX_DELAY, reconnectDelay * 1.6);
  }

  // Slider positions are cosmetic HTML defaults until the server tells us what
  // it is ACTUALLY running. Without this the panel can display a stale value
  // (e.g. "15") while the engine runs 55 -- which made a calibration session
  // read as broken when it was fine. Sync once, then leave the operator alone.
  function syncSliders(msg) {
    if (msg.temperature == null) return;
    const fromServer = {
      temperature: msg.temperature,
      floor: msg.floor,
      fam_low_sim: msg.fam_low_sim,
      fam_high_sim: msg.fam_high_sim,
    };
    Object.keys(fromServer).forEach(function (field) {
      const value = fromServer[field];
      if (value == null) return;
      const input = document.querySelector('input[data-field="' + field + '"]');
      if (!input) return;
      // never yank a control out from under the operator mid-drag
      if (document.activeElement === input) return;
      // widen the track if the real value sits outside the authored range,
      // otherwise the browser clamps it and a nudge would wreck the calibration
      if (Number(value) > Number(input.max)) input.max = value;
      if (Number(value) < Number(input.min)) input.min = value;
      input.value = value;
      const out = document.getElementById("out-" + field);
      if (out) {
        const isFloatField =
          ["floor", "fam_low_sim", "fam_high_sim"].indexOf(field) !== -1;
        out.textContent = isFloatField ? Number(value).toFixed(3) : value;
      }
    });
  }

  function sendTune(field, value) {
    const sock = window.__foolbotWS;
    if (!sock || sock.readyState !== WebSocket.OPEN) return;
    const payload = { type: "tune" };
    payload[field] = value;        // only the changed field
    sock.send(JSON.stringify(payload));
  }

  // ---- Tuning sliders ---------------------------------------------------
  function wireSliders() {
    document.querySelectorAll('.tune-grid input[type="range"]').forEach(function (input) {
      const field = input.dataset.field;
      const out = document.getElementById("out-" + field);
      const isFloatField = ["floor", "fam_low_sim", "fam_high_sim"].indexOf(field) !== -1;
      const fmt = function (v) { return isFloatField ? Number(v).toFixed(3) : v; };
      if (out) out.textContent = fmt(input.value);
      input.addEventListener("input", function () {
        const value = Number(input.value);
        if (out) out.textContent = fmt(value);
        sendTune(field, value); // field name matches contract (note: "floor")
      });
    });
  }

  // ---- Tuning panel open/closed ----------------------------------------
  // Ships closed so the child-facing screen is clean, but a calibration
  // session reloads the page constantly and re-opening it every time was
  // needless friction -- so the operator's choice sticks.
  function wireTuningPanel() {
    const panel = document.getElementById("tuning");
    if (!panel) return;
    try {
      if (localStorage.getItem("foolbot.tuningOpen") === "1") panel.open = true;
    } catch (e) { /* private mode / disabled storage: just stay closed */ }
    panel.addEventListener("toggle", function () {
      try { localStorage.setItem("foolbot.tuningOpen", panel.open ? "1" : "0"); }
      catch (e) {}
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "t" && e.key !== "T") return;
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      panel.open = !panel.open;
    });
  }

  wireSliders();
  wireTuningPanel();
  wireArmControls();
  connect();
})();
