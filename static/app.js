// EPOCH WebUI — gritty cockpit. Live input mirror in the center.

(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);

  let armed = false;
  let armedAt = null;
  let cmdCount = 0;          // bumped on every drive packet (informational)
  let demoRunning = false;
  let ws = null;
  let pingTimer = null;
  let throttlePct = 0;   // -100..100
  let steerPct = 0;      // -100..100

  // Toggle state for buttons that have proper on/off semantics
  const toggleState = { 'led': false, 'smoke': false, 'armor': false, 'cannon': false };

  function vibrate(ms) {
    try { if (navigator.vibrate) navigator.vibrate(ms); } catch (_) {}
  }

  // ---- Status / arm ----------------------------------------------------------

  async function fetchStatus() {
    try {
      const r = await fetch('/api/status');
      const s = await r.json();
      armed = !!s.armed;
      armedAt = s.armed_at;
      demoRunning = !!s.demo_running;
      renderArmState();
      renderDemoState();
      renderSounds(s.sounds || {});
    } catch (_) {}
  }

  async function arm() {
    setArmBtnBusy(true, 'ARMING');
    try {
      const r = await fetch('/api/arm', { method: 'POST' });
      const data = await r.json();
      if (!r.ok) {
        setHud('FAULT');
        alert('Arm failed: ' + (data.detail || r.status));
        return;
      }
      armed = !!data.armed;
      armedAt = data.armed_at;
      renderArmState();
      if (armed) { flashHud('ONLINE'); connectWS(); }
    } catch (e) {
      setHud('ERROR');
      alert('Arm error: ' + e.message);
    } finally { setArmBtnBusy(false); }
  }

  async function disarm() {
    setArmBtnBusy(true, 'SHUTDOWN');
    flashHud('SHUTDOWN');
    try {
      disconnectWS();
      const r = await fetch('/api/disarm', { method: 'POST' });
      const data = await r.json();
      armed = !!data.armed;
      armedAt = data.armed_at;
      Object.keys(toggleState).forEach(k => toggleState[k] = false);
      syncSilhouette();
      renderArmState();
    } catch (e) {
      alert('Disarm error: ' + e.message);
    } finally { setArmBtnBusy(false); }
  }

  function renderArmState() {
    const btn = $('armBtn');
    const demoBtn = $('demoBtn');
    if (armed) {
      btn.querySelector('.armBtn-text').textContent = 'DISARM';
      btn.classList.add('armed');
      if (demoBtn) demoBtn.disabled = false;
      setHud('ONLINE');
    } else {
      btn.querySelector('.armBtn-text').textContent = 'ARM';
      btn.classList.remove('armed');
      if (demoBtn) demoBtn.disabled = true;
      setHud('STANDBY');
    }
  }

  function renderDemoState() {
    const btn = $('demoBtn');
    if (!btn) return;
    btn.classList.toggle('running', demoRunning);
    btn.querySelector('.demoBtn-text').textContent = demoRunning ? 'RUNNING' : 'DEMO';
  }

  async function startDemo() {
    if (!armed || demoRunning) return;
    try {
      const r = await fetch('/api/demo', { method: 'POST' });
      if (r.ok) {
        demoRunning = true;
        renderDemoState();
        bumpCmdEvent();
        flashHud('DEMO');
      }
    } catch (_) {}
  }

  function setArmBtnBusy(busy, busyText) {
    const btn = $('armBtn');
    btn.disabled = busy;
    const t = btn.querySelector('.armBtn-text');
    if (busy) t.textContent = busyText || '...';
    else t.textContent = armed ? 'DISARM' : 'ARM';
  }

  function setHud(msg) { $('hudStatus').textContent = msg; }
  function flashHud(msg) {
    setHud(msg);
    setTimeout(() => setHud(armed ? 'ONLINE' : 'IDLE'), 1500);
  }

  // ---- Mirror tick (timer + cmd counter) ------------------------------------

  function fmtDuration(secs) {
    if (secs == null || isNaN(secs) || secs < 0) return '00:00:00';
    const s = Math.floor(secs);
    const h = String(Math.floor(s / 3600)).padStart(2, '0');
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    return `${h}:${m}:${ss}`;
  }
  function tickHud() {
    if (armed && armedAt != null) {
      $('missionTimer').textContent = fmtDuration(Date.now() / 1000 - armedAt);
    } else {
      $('missionTimer').textContent = '00:00:00';
    }
    $('cmdCount').textContent = String(cmdCount).padStart(3, '0');
  }
  setInterval(tickHud, 250);

  // ---- Live input mirror — driven by joystick ------------------------------

  function fmtSigned(v) {
    const sign = v >= 0 ? '+' : '-';
    const abs = Math.abs(Math.round(v)).toString().padStart(3, '0');
    return sign + abs;
  }

  function vectorLabel(t, s) {
    const fwd = Math.abs(t) > 8;
    const turn = Math.abs(s) > 8;
    if (!fwd && !turn) return 'IDLE';
    const dir = t < 0 ? 'REV' : 'FWD';
    if (!turn) return dir;
    const side = s < 0 ? 'L' : 'R';
    if (!fwd) return `TURN-${side}`;
    return `${dir}-${side}`;
  }

  function updateMirror() {
    const t = clamp(throttlePct, -100, 100);
    const s = clamp(steerPct,    -100, 100);

    $('thrValue').textContent = fmtSigned(t);
    $('strValue').textContent = fmtSigned(s);

    const vs = $('vectorState');
    if (vs) {
      const label = vectorLabel(t, s);
      vs.textContent = label;
      vs.classList.remove('idle', 'fwd', 'rev');
      if (label === 'IDLE')             vs.classList.add('idle');
      else if (label.startsWith('REV')) vs.classList.add('rev');
      else                              vs.classList.add('fwd');
    }

    // Silhouette body lean — translate forward/back, rotate by steer
    const bm = $('batmobile');
    if (bm) {
      const ty = -t * 0.10;   // forward = up on screen
      const rot = s * 0.06;   // steer right = lean right
      bm.style.transform = `translateY(${ty.toFixed(1)}px) rotate(${rot.toFixed(2)}deg)`;
      bm.classList.toggle('reversing', t < -8);
    }

    // Drive-vector line inside the cockpit
    const line = $('vectorLine');
    const dot  = $('vectorDot');
    if (line && dot) {
      const mag = Math.hypot(t, s) / 100;          // 0..1.41
      const len = Math.min(mag, 1) * 60;            // up to 60 px of line
      const angleRad = Math.atan2(s, -t);           // 0=fwd, π=rev, +=right
      const x = Math.sin(angleRad) * len;
      const y = -Math.cos(angleRad) * len;
      line.setAttribute('x2', x.toFixed(1));
      line.setAttribute('y2', y.toFixed(1));
      const visible = mag > 0.05 ? 1 : 0;
      line.setAttribute('opacity', visible);
      dot.setAttribute('opacity',  visible);
    }
  }

  // ---- WebSocket drive stream ------------------------------------------------

  function connectWS() {
    if (ws && ws.readyState <= 1) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/drive`);
    ws.onopen = () => { pingTimer = setInterval(sendDrive, 100); };
    ws.onclose = () => {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      if (armed) setTimeout(connectWS, 1000);
    };
    ws.onerror = () => {};
  }
  function disconnectWS() {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    if (ws) { try { ws.close(); } catch (_) {} ws = null; }
  }
  function sendDrive() {
    if (!ws || ws.readyState !== 1) return;
    const throttle = 100 + Math.round(clamp(throttlePct, -100, 100));
    const steering = 100 + Math.round(clamp(steerPct,    -100, 100));
    const start = performance.now();
    ws.send(JSON.stringify({ type: 'drive', throttle, steering }));
    const lat = Math.round(performance.now() - start);
    $('latencyVal').textContent = (lat < 1000 ? lat : '999') + 'ms';
    if (throttlePct !== 0 || steerPct !== 0) bumpCmd();
  }
  function bumpCmd() { cmdCount++; }

  // No-op shim — TRACE/badge UI was removed. Kept so callers don't need
  // conditional checks; if a future inline log surface lands, wire it here.
  function bumpCmdEvent() { /* intentionally empty */ }

  // Brief flash on a button after a successful network action
  function flashSuccess(btn) {
    if (!btn) return;
    btn.classList.remove('flash');
    void btn.offsetWidth;  // restart animation
    btn.classList.add('flash');
    setTimeout(() => btn.classList.remove('flash'), 500);
  }

  // ---- Telemetry poll (link signal + RTT + temp) ----------------------------

  function renderTelemetry(t) {
    const dbm = t.link?.signal_dbm;
    const rate = t.link?.bitrate_mbps;

    if ($('linkVal')) {
      if (dbm == null) {
        $('linkVal').textContent = 'NO LINK';
      } else {
        $('linkVal').textContent = `${dbm}dBm` + (rate ? ` ${Math.round(rate)}M` : '');
      }
    }

    const rtt = t.rtt_ms;
    if ($('rttVal')) {
      $('rttVal').textContent = rtt == null ? '---' : `${Math.round(rtt)}ms`;
    }
  }

  async function fetchTelemetry() {
    try {
      const r = await fetch('/api/telemetry');
      if (!r.ok) return;
      const t = await r.json();
      renderTelemetry(t);
    } catch (_) {}
  }
  setInterval(fetchTelemetry, 2000);

  // ---- Joysticks -------------------------------------------------------------

  function setupStick(rootId, axis, callback) {
    const root = $(rootId);
    const knob = root.querySelector('.knob');
    const ring = root.querySelector('.ring');
    let active = null;
    let cx = 0, cy = 0, radius = 0;
    let parked = false;       // when true, knob stays at last value on release
    let lastKx = 0, lastKy = 0;

    function recalc() {
      const r = ring.getBoundingClientRect();
      cx = r.left + r.width / 2;
      cy = r.top + r.height / 2;
      radius = (r.width / 2) - 28;
    }
    recalc();
    window.addEventListener('resize', recalc);
    window.addEventListener('orientationchange', recalc);

    function setKnob(dx, dy) {
      const max = radius;
      const dist = Math.hypot(dx, dy);
      let kx = dx, ky = dy;
      if (dist > max) {
        kx = dx * max / dist;
        ky = dy * max / dist;
      }
      lastKx = kx; lastKy = ky;
      knob.style.left = `${50 + (kx / max) * 50 * 0.8}%`;
      knob.style.top  = `${50 + (ky / max) * 50 * 0.8}%`;
      const pct = ((axis === 'y' ? -ky : kx) / max) * 100;
      callback(clamp(pct, -100, 100));
    }
    function reset() {
      knob.style.left = '50%';
      knob.style.top = '50%';
      lastKx = 0; lastKy = 0;
      callback(0);
      root.classList.remove('parked');
    }
    root.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (active !== null) return;
      // Tap-to-release a parked stick (no shift): clear and return to center
      if (parked && !e.shiftKey) {
        parked = false;
        reset();
        vibrate(8);
        return;
      }
      active = e.pointerId;
      root.setPointerCapture(active);
      recalc();
      setKnob(e.clientX - cx, e.clientY - cy);
      vibrate(8);
    });
    root.addEventListener('pointermove', (e) => {
      if (active !== e.pointerId) return;
      e.preventDefault();
      setKnob(e.clientX - cx, e.clientY - cy);
    });
    const release = (e) => {
      if (active !== e.pointerId) return;
      try { root.releasePointerCapture(active); } catch (_) {}
      active = null;
      // Hold Shift while releasing → park the stick at the current value
      if (e.shiftKey) {
        parked = true;
        root.classList.add('parked');
        vibrate(20);
      } else {
        parked = false;
        reset();
        vibrate(8);
      }
    };
    root.addEventListener('pointerup', release);
    root.addEventListener('pointercancel', release);
    root.addEventListener('pointerleave', release);
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // ---- Effect buttons --------------------------------------------------------

  function bindEffects() {
    document.querySelectorAll('[data-action]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const a = btn.dataset.action;
        if (!armed) { flashLabel(btn, 'NO ARM'); return; }
        try {
          let r;
          if (a === 'led-toggle') {
            const next = !toggleState['led'];
            r = await fetch(`/api/led?on=${next}`, { method: 'POST' });
            if (r.ok) toggleState['led'] = next;
          }
          else if (a === 'smoke-toggle') {
            const next = !toggleState['smoke'];
            r = await fetch(`/api/smoke?on=${next}`, { method: 'POST' });
            if (r.ok) toggleState['smoke'] = next;
          }
          else if (a === 'armor') {
            r = await fetch('/api/armor', { method: 'POST' });
            if (r.ok) toggleState['armor'] = !toggleState['armor'];
          }
          else if (a === 'gun-up') {
            r = await fetch('/api/gun_up', { method: 'POST' });
            if (r.ok) toggleState['cannon'] = !toggleState['cannon'];
          }
          else if (a === 'fire') {
            r = await fetch('/api/fire', { method: 'POST' });
          }
          if (r && r.ok) {
            bumpCmd();
            bumpCmdEvent();
            flashSuccess(btn);
            vibrate(a === 'fire' ? 30 : 12);
          }
          syncSilhouette();
          if (r && r.ok && a === 'fire') triggerFire();
        } catch (e) { flashLabel(btn, 'ERR'); }
      });
    });
  }

  function syncSilhouette() {
    const bm = $('batmobile');
    if (bm) {
      bm.classList.toggle('lamps-on',   toggleState['led']);
      bm.classList.toggle('smoke-on',   toggleState['smoke']);
      bm.classList.toggle('armor-open', toggleState['armor']);
      bm.classList.toggle('cannon-up',  toggleState['cannon']);
    }
    document.querySelectorAll('[data-action]').forEach((btn) => {
      const a = btn.dataset.action;
      if (a === 'led-toggle')   btn.dataset.state  = toggleState['led']    ? 'on' : 'off';
      if (a === 'smoke-toggle') btn.dataset.state  = toggleState['smoke']  ? 'on' : 'off';
      if (a === 'armor')        btn.dataset.toggle = toggleState['armor']  ? 'on' : 'off';
      if (a === 'gun-up')       btn.dataset.toggle = toggleState['cannon'] ? 'on' : 'off';
    });
  }

  function triggerFire() {
    const bm = $('batmobile');
    if (!bm) return;
    bm.classList.add('fire-flash');
    setTimeout(() => bm.classList.remove('fire-flash'), 280);
  }

  // Backwards-compat shim — older code paths called updateLEDs()
  function updateLEDs() { syncSilhouette(); }
  function flashLabel(btn, msg) {
    const lbl = btn.querySelector('.fx-name') || btn.querySelector('.armBtn-text') || btn.querySelector('.demoBtn-text');
    if (!lbl) return;
    const orig = lbl.textContent || '';
    if (orig) {
      lbl.textContent = msg;
      setTimeout(() => { lbl.textContent = orig; }, 800);
    }
  }

  // ---- Sounds ---------------------------------------------------------------

  function renderSounds(catalog) {
    const list = $('soundList');
    list.innerHTML = '';
    const indices = Object.keys(catalog).map(Number).sort((a, b) => a - b);
    if (indices.length === 0) {
      for (let i = 1; i <= 16; i++) indices.push(i);
    }
    indices.forEach((i) => {
      const b = document.createElement('button');
      b.className = 'sound';
      b.textContent = catalog[i] ? `${i.toString().padStart(2,'0')} · ${catalog[i]}` : `FX-${i.toString().padStart(2,'0')}`;
      b.addEventListener('click', async () => {
        if (!armed) { b.textContent = 'NO ARM'; setTimeout(() => renderSounds(catalog), 700); return; }
        try {
          const r = await fetch(`/api/sound/${i}`, { method: 'POST' });
          if (r.ok) {
            bumpCmd();
            bumpCmdEvent();
            flashSuccess(b);
            vibrate(8);
          }
        } catch (_) {}
      });
      list.appendChild(b);
    });
  }

  // ---- Init -----------------------------------------------------------------

  // ---- Keyboard controls (desktop) ------------------------------------------

  // Throttle/steer accumulators while keys are held; pulse to 0 on release.
  const keyState = { w: false, s: false, a: false, d: false };
  function applyKeyDrive() {
    if (!armed) return;
    const t = (keyState.w ? 80 : 0) - (keyState.s ? 80 : 0);
    const s = (keyState.d ? 80 : 0) - (keyState.a ? 80 : 0);
    throttlePct = t;
    steerPct = s;
    updateMirror();
  }

  function bindKeyboard() {
    const dispatchEffect = (action) => {
      const btn = document.querySelector(`[data-action="${action}"]`);
      if (btn) btn.click();
    };

    document.addEventListener('keydown', (e) => {
      // Don't hijack typing in inputs (none today, but future-proof)
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.repeat) return;

      const k = e.key.toLowerCase();
      // Lifecycle / panels — work even when disarmed
      if (k === 'escape')          { if (armed) disarm(); else { $('fxPanel').classList.add('hidden'); } return; }
      if (k === '/')               { $('fxBtn').click();  return; }

      if (!armed) return;

      // Drive
      if (k === 'w' || k === 'arrowup')    { keyState.w = true; applyKeyDrive(); e.preventDefault(); return; }
      if (k === 's' || k === 'arrowdown')  { keyState.s = true; applyKeyDrive(); e.preventDefault(); return; }
      if (k === 'a' || k === 'arrowleft')  { keyState.a = true; applyKeyDrive(); e.preventDefault(); return; }
      if (k === 'd' || k === 'arrowright') { keyState.d = true; applyKeyDrive(); e.preventDefault(); return; }
      if (k === ' ')                       { throttlePct = 0; steerPct = 0; updateMirror(); fetch('/api/stop', { method: 'POST' }); e.preventDefault(); return; }

      // Effects
      if (k === 'l') { dispatchEffect('led-toggle');   return; }
      if (k === 'k') { dispatchEffect('smoke-toggle'); return; }
      if (k === 'm') { dispatchEffect('armor');        return; }
      if (k === 'g') { dispatchEffect('gun-up');       return; }
      if (k === 'f') { dispatchEffect('fire');         return; }

      // FX bank by digit (1-9)
      if (/^[1-9]$/.test(k)) {
        const idx = parseInt(k, 10);
        const btn = document.querySelectorAll('#soundList .sound')[idx - 1];
        if (btn) btn.click();
      }
    });

    document.addEventListener('keyup', (e) => {
      const k = e.key.toLowerCase();
      if (k === 'w' || k === 'arrowup')    { keyState.w = false; applyKeyDrive(); }
      if (k === 's' || k === 'arrowdown')  { keyState.s = false; applyKeyDrive(); }
      if (k === 'a' || k === 'arrowleft')  { keyState.a = false; applyKeyDrive(); }
      if (k === 'd' || k === 'arrowright') { keyState.d = false; applyKeyDrive(); }
    });

    // Releasing focus (alt-tab etc) should drop drive to safe zero
    window.addEventListener('blur', () => {
      Object.keys(keyState).forEach(k => keyState[k] = false);
      if (armed) applyKeyDrive();
    });
  }

  // Dead-man-switch ABORT — press and hold ~700ms to confirm full-stop.
  // Releasing before the fill completes cancels safely.
  const ABORT_HOLD_MS = 700;
  function setupAbortDeadMan() {
    const btn = $('estop');
    if (!btn) return;
    let timer = null;
    let active = false;

    function fire() {
      throttlePct = 0; steerPct = 0;
      updateMirror();
      flashHud('ABORT');
      btn.classList.add('fired');
      setTimeout(() => btn.classList.remove('fired'), 400);
      vibrate(80);
      fetch('/api/stop', { method: 'POST' })
        .then((r) => { if (r && r.ok) { bumpCmd(); bumpCmdEvent(); } })
        .catch(() => {});
    }

    function start(e) {
      if (!armed || active) return;
      e.preventDefault();
      active = true;
      btn.classList.add('holding');
      btn.setPointerCapture && e.pointerId != null && btn.setPointerCapture(e.pointerId);
      vibrate(8);
      timer = setTimeout(() => {
        timer = null;
        if (!active) return;
        active = false;
        btn.classList.remove('holding');
        fire();
      }, ABORT_HOLD_MS);
    }

    function cancel(e) {
      if (!active) return;
      active = false;
      btn.classList.remove('holding');
      if (timer) { clearTimeout(timer); timer = null; }
      try { e.pointerId != null && btn.releasePointerCapture(e.pointerId); } catch (_) {}
    }

    btn.addEventListener('pointerdown', start);
    btn.addEventListener('pointerup', cancel);
    btn.addEventListener('pointercancel', cancel);
    btn.addEventListener('pointerleave', cancel);
    btn.addEventListener('click', (e) => e.preventDefault());

    // Keyboard: Space (existing) is the instant abort path. Esc disarms.
    // The dead-man hold is mouse/touch only — keys keep their fast paths.
  }

  function init() {
    $('armBtn').addEventListener('click', () => armed ? disarm() : arm());
    $('demoBtn').addEventListener('click', startDemo);
    setupAbortDeadMan();
    function setFxDrawer(open) {
      $('fxPanel').classList.toggle('hidden', !open);
      $('fxBtn').classList.toggle('active', open);
      $('fxBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    $('fxBtn').addEventListener('click', () => {
      setFxDrawer($('fxPanel').classList.contains('hidden'));
    });
    $('fxClose').addEventListener('click', () => setFxDrawer(false));

    setupStick('leftStick', 'y', (v) => { throttlePct = v; updateMirror(); });
    setupStick('rightStick', 'x', (v) => { steerPct = v; updateMirror(); });

    bindEffects();
    bindKeyboard();
    fetchStatus();
    fetchTelemetry();
    setInterval(fetchStatus, 5000);
    updateMirror();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
