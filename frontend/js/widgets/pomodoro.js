// Pomodoro / Stoppuhr — pure frontend, state in localStorage.
// No backend module: ticks via setInterval, persists across page reloads.
// Anchor timestamps use Date.now() (wall-clock) so a reload while running
// keeps the elapsed time accurate.

import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

const LS_KEY = "edge.pomodoro.state";

const DEFAULT_OPTS = {
  work_minutes: 25,
  short_break: 5,
  long_break: 15,
  long_every: 4,
};

const PHASE_KEYS = {
  work: "widget.pomodoro.phase.work",
  short_break: "widget.pomodoro.phase.short_break",
  long_break: "widget.pomodoro.phase.long_break",
};

function fmt(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

class PomodoroWidget {
  static modules = [];

  mount(el, _data, meta) {
    this.el = el;
    el.classList.add("pomodoro-widget");
    this.opts = { ...DEFAULT_OPTS, ...(meta?.options || {}) };
    this.state = this._restore() ?? this._initial();
    this._audio = null;

    el.innerHTML = `
      <div class="pomo-modebar">
        <button class="pomo-mode" data-mode="pomodoro" type="button">${t("widget.pomodoro.mode.pomodoro")}</button>
        <button class="pomo-mode" data-mode="stopwatch" type="button">${t("widget.pomodoro.mode.stopwatch")}</button>
      </div>
      <div class="pomo-phase" data-bind="phase"></div>
      <div class="pomo-time" data-bind="time">00:00</div>
      <div class="pomo-controls">
        <button class="pomo-btn pomo-primary" data-act="toggle" type="button">${t("widget.pomodoro.start")}</button>
        <button class="pomo-btn" data-act="reset" type="button">${t("widget.pomodoro.reset")}</button>
        <button class="pomo-btn pomo-skip" data-act="skip" type="button" hidden>${t("widget.pomodoro.skip")}</button>
      </div>
    `;

    for (const btn of el.querySelectorAll("[data-mode]")) {
      btn.addEventListener("click", () => this._switchMode(btn.dataset.mode));
    }
    el.querySelector('[data-act="toggle"]').addEventListener("click", () => this._toggle());
    el.querySelector('[data-act="reset"]').addEventListener("click", () => this._reset());
    el.querySelector('[data-act="skip"]').addEventListener("click", () => this._skip());

    this._timer = setInterval(() => this._tick(), 200);
    // Catch a stale anchor right after restore (e.g. phase elapsed during a
    // page reload): one synchronous tick advances state before the user sees it.
    this._tick();
  }

  destroy() {
    clearInterval(this._timer);
  }

  // ----------------------------------------------------- state machine

  _initial() {
    return {
      mode: "pomodoro",
      phase: "work",
      cycle: 1,
      remaining_ms: this.opts.work_minutes * 60_000,
      running: false,
      // when running: wall-clock at start/resume + remaining_ms snapshot at that anchor
      anchor_ts: null,
      anchor_remaining_ms: null,
      // stopwatch
      sw_elapsed_ms: 0,
      sw_anchor_ts: null,
    };
  }

  _switchMode(mode) {
    if (this.state.mode === mode) return;
    if (this.state.running) this._pause();
    this.state.mode = mode;
    this._persist();
    this._render();
  }

  _toggle() {
    this._ensureAudio();
    if (this.state.running) this._pause();
    else this._start();
  }

  _start() {
    const now = Date.now();
    if (this.state.mode === "pomodoro") {
      this.state.anchor_ts = now;
      this.state.anchor_remaining_ms = this.state.remaining_ms;
    } else {
      this.state.sw_anchor_ts = now;
    }
    this.state.running = true;
    this._persist();
    this._render();
  }

  _pause() {
    const now = Date.now();
    if (this.state.mode === "pomodoro") {
      const elapsed = now - (this.state.anchor_ts ?? now);
      this.state.remaining_ms = Math.max(
        0, (this.state.anchor_remaining_ms ?? this.state.remaining_ms) - elapsed,
      );
      this.state.anchor_ts = null;
      this.state.anchor_remaining_ms = null;
    } else {
      const elapsed = now - (this.state.sw_anchor_ts ?? now);
      this.state.sw_elapsed_ms += elapsed;
      this.state.sw_anchor_ts = null;
    }
    this.state.running = false;
    this._persist();
    this._render();
  }

  _reset() {
    this.state.running = false;
    this.state.anchor_ts = null;
    this.state.anchor_remaining_ms = null;
    if (this.state.mode === "pomodoro") {
      this.state.phase = "work";
      this.state.cycle = 1;
      this.state.remaining_ms = this.opts.work_minutes * 60_000;
    } else {
      this.state.sw_elapsed_ms = 0;
      this.state.sw_anchor_ts = null;
    }
    this._persist();
    this._render();
  }

  _skip() {
    if (this.state.mode !== "pomodoro") return;
    this._advancePhase(false);
  }

  _advancePhase(playCue) {
    const wasRunning = this.state.running;
    if (wasRunning) this._pause();

    if (this.state.phase === "work") {
      const isLong = this.state.cycle >= this.opts.long_every;
      this.state.phase = isLong ? "long_break" : "short_break";
      const mins = isLong ? this.opts.long_break : this.opts.short_break;
      this.state.remaining_ms = mins * 60_000;
    } else {
      this.state.cycle = this.state.phase === "long_break" ? 1 : this.state.cycle + 1;
      this.state.phase = "work";
      this.state.remaining_ms = this.opts.work_minutes * 60_000;
    }
    this._persist();
    this._render();
    if (playCue) this._cue();
    if (wasRunning) this._start();
  }

  _tick() {
    if (!this.state.running) {
      this._render();
      return;
    }
    const now = Date.now();
    if (this.state.mode === "pomodoro") {
      const elapsed = now - (this.state.anchor_ts ?? now);
      const remaining = Math.max(
        0, (this.state.anchor_remaining_ms ?? this.state.remaining_ms) - elapsed,
      );
      this.state.remaining_ms = remaining;
      if (remaining <= 0) {
        this._advancePhase(true);
        return;
      }
    }
    this._render();
  }

  // ----------------------------------------------------- persistence

  _persist() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(this.state));
    } catch (_err) {
      /* localStorage may be disabled — ignore */
    }
  }

  _restore() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return null;
      const s = JSON.parse(raw);
      // Anchors use Date.now() so they remain valid after reload.
      return s;
    } catch (_err) {
      return null;
    }
  }

  // ----------------------------------------------------- audio + visual cue

  _ensureAudio() {
    // Browsers require a user gesture before AudioContext starts producing
    // sound — _toggle() is always behind a tap, so this is the right hook.
    if (this._audio) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) this._audio = new Ctx();
    } catch (_err) {
      this._audio = null;
    }
  }

  _cue() {
    if (this._audio) {
      const t0 = this._audio.currentTime;
      for (let i = 0; i < 3; i++) {
        const osc = this._audio.createOscillator();
        const gain = this._audio.createGain();
        osc.frequency.value = 880;
        osc.type = "sine";
        osc.connect(gain).connect(this._audio.destination);
        const t = t0 + i * 0.25;
        gain.gain.setValueAtTime(0.0001, t);
        gain.gain.exponentialRampToValueAtTime(0.25, t + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
        osc.start(t);
        osc.stop(t + 0.2);
      }
    }
    this.el.classList.add("pomo-flash");
    setTimeout(() => this.el.classList.remove("pomo-flash"), 1200);
  }

  // ----------------------------------------------------- render

  _render() {
    const root = this.el;
    for (const btn of root.querySelectorAll("[data-mode]")) {
      btn.classList.toggle("is-active", btn.dataset.mode === this.state.mode);
    }
    const phaseEl = root.querySelector('[data-bind="phase"]');
    const timeEl = root.querySelector('[data-bind="time"]');
    const skipBtn = root.querySelector('[data-act="skip"]');
    const toggleBtn = root.querySelector('[data-act="toggle"]');

    if (this.state.mode === "pomodoro") {
      phaseEl.textContent =
        `${t(PHASE_KEYS[this.state.phase])} · ${this.state.cycle}/${this.opts.long_every}`;
      phaseEl.dataset.phase = this.state.phase;
      skipBtn.hidden = false;
      timeEl.textContent = fmt(this.state.remaining_ms);
    } else {
      phaseEl.textContent = t("widget.pomodoro.stopwatch_label");
      delete phaseEl.dataset.phase;
      skipBtn.hidden = true;
      let elapsed = this.state.sw_elapsed_ms;
      if (this.state.running && this.state.sw_anchor_ts != null) {
        elapsed += Date.now() - this.state.sw_anchor_ts;
      }
      timeEl.textContent = fmt(elapsed);
    }
    toggleBtn.textContent = this.state.running ? t("widget.pomodoro.pause") : t("widget.pomodoro.start");
    toggleBtn.classList.toggle("is-running", this.state.running);
  }
}

registerWidget("pomodoro", PomodoroWidget);
