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
  function applyBand(band) {
    const b = BANDS[band] || BANDS.idle;
    el.root.style.setProperty("--band", b.color);
    el.root.style.setProperty("--band-glow", b.glow);
    el.caption.textContent = b.caption;
  }

  function showIdle(isIdle) {
    el.idle.classList.toggle("hidden", !isIdle);
  }

  function handleResult(msg) {
    // Live operator readout (always update if provided).
    if (msg.raw_top_label != null) el.rawLabel.textContent = msg.raw_top_label;
    if (msg.raw_top_sim != null)   el.rawSim.textContent = Number(msg.raw_top_sim).toFixed(3);

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

  function setConn(up) {
    el.conn.textContent = up ? "● live" : "reconnecting…";
    el.conn.className = "conn " + (up ? "conn--up" : "conn--down");
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

  wireSliders();
  connect();
})();
