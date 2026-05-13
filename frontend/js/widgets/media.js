import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

const US_PER_S = 1_000_000;

function fmtTime(us) {
  if (!Number.isFinite(us) || us <= 0) return "0:00";
  const total = Math.floor(us / US_PER_S);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

class MediaWidget {
  static modules = ["media"];

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="media-art">
        <img class="media-art-img" alt="" hidden>
        <div class="media-art-placeholder" aria-hidden="true">♪</div>
      </div>
      <div class="media-info">
        <div class="media-meta">
          <div class="media-player" data-bind="player"></div>
          <div class="media-title" data-bind="title">${t("widget.media.no_active_player")}</div>
          <div class="media-artist" data-bind="artist"></div>
        </div>
        <div class="media-scrubber">
          <input type="range" min="0" max="1000" value="0" step="1"
                 data-bind="scrubber" aria-label="${t("widget.media.position")}">
          <div class="media-times">
            <span data-bind="position">0:00</span>
            <span data-bind="length">0:00</span>
          </div>
        </div>
        <div class="media-controls">
          <button type="button" class="media-toggle" data-action="shuffle" aria-label="${t("widget.media.shuffle")}">
            <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/></svg>
          </button>
          <button type="button" data-action="prev" aria-label="${t("widget.media.prev")}">
            <svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M6 6h2v12H6V6zm3.5 6L20 18V6L9.5 12z"/></svg>
          </button>
          <button type="button" class="media-play" data-action="play_pause" aria-label="${t("widget.media.play_pause")}">
            <svg class="media-icon-play" viewBox="0 0 24 24" width="26" height="26"><path fill="currentColor" d="M8 5v14l11-7-11-7z"/></svg>
            <svg class="media-icon-pause" viewBox="0 0 24 24" width="26" height="26" hidden><path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>
          </button>
          <button type="button" data-action="next" aria-label="${t("widget.media.next")}">
            <svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M16 6h2v12h-2V6zM4 6l10.5 6L4 18V6z"/></svg>
          </button>
          <button type="button" class="media-toggle media-loop" data-action="loop" aria-label="${t("widget.media.loop")}">
            <svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>
            <span class="media-loop-badge" aria-hidden="true">1</span>
          </button>
        </div>
      </div>
    `;

    this._lastUpdate = null;
    this._scrubbing = false;
    this._currentToken = null;

    for (const btn of this.el.querySelectorAll("[data-action]")) {
      btn.addEventListener("click", () => this._onAction(btn.dataset.action));
    }

    const scrubber = this.el.querySelector('[data-bind="scrubber"]');
    scrubber.addEventListener("pointerdown", () => {
      this._scrubbing = true;
    });
    scrubber.addEventListener("change", (e) => {
      const fraction = Number(e.target.value) / 1000;
      this._sendSeek(fraction);
      this._scrubbing = false;
    });
    scrubber.addEventListener("pointercancel", () => {
      this._scrubbing = false;
    });

    this._timer = setInterval(() => this._tick(), 250);
  }

  update(data) {
    if (!data?.available) {
      return this._renderIdle(data?.reason || t("widget.media.unavailable"));
    }
    if (!data.active) {
      return this._renderIdle(t("widget.media.no_active_player_short"));
    }
    this._lastUpdate = data;
    this.el.classList.remove("widget-disabled");

    this.el.querySelector('[data-bind="player"]').textContent = data.player || "";
    this.el.querySelector('[data-bind="title"]').textContent = data.title || "—";
    this.el.querySelector('[data-bind="artist"]').textContent =
      data.artist || data.album || "";

    if (data.art_token !== this._currentToken) {
      this._currentToken = data.art_token;
      const img = this.el.querySelector(".media-art-img");
      const placeholder = this.el.querySelector(".media-art-placeholder");
      if (data.art_token) {
        img.onerror = () => {
          img.hidden = true;
          placeholder.hidden = false;
        };
        img.onload = () => {
          img.hidden = false;
          placeholder.hidden = true;
        };
        img.src = `/api/media/art/${encodeURIComponent(data.art_token)}`;
      } else {
        img.hidden = true;
        img.removeAttribute("src");
        placeholder.hidden = false;
      }
    }

    const playing = data.playback_status === "Playing";
    this.el.querySelector(".media-icon-play").hidden = playing;
    this.el.querySelector(".media-icon-pause").hidden = !playing;

    this._setEnabled('[data-action="prev"]', data.can_prev);
    this._setEnabled('[data-action="next"]', data.can_next);
    this._setEnabled('[data-action="play_pause"]', data.can_play || data.can_pause);
    this.el.querySelector('[data-bind="scrubber"]').disabled = !data.can_seek;

    // Shuffle / repeat state
    const shuffleBtn = this.el.querySelector('[data-action="shuffle"]');
    shuffleBtn.classList.toggle("is-active", !!data.shuffle);

    const loopBtn = this.el.querySelector('[data-action="loop"]');
    const status = data.loop_status || "None";
    loopBtn.dataset.state = status;
    loopBtn.classList.toggle("is-active", status !== "None");
    // Badge "1" is shown only when repeating a single track; CSS keys off
    // the data-state attribute, so no JS toggling needed.

    this._tick();
  }

  _setEnabled(selector, enabled) {
    const btn = this.el.querySelector(selector);
    if (btn) btn.disabled = !enabled;
  }

  _renderIdle(reason) {
    this.el.classList.add("widget-disabled");
    this._lastUpdate = null;
    this.el.querySelector('[data-bind="player"]').textContent = "";
    this.el.querySelector('[data-bind="title"]').textContent = t("widget.media.no_active_player");
    this.el.querySelector('[data-bind="artist"]').textContent = reason || "";
    this.el.querySelector('[data-bind="position"]').textContent = "0:00";
    this.el.querySelector('[data-bind="length"]').textContent = "0:00";
    this.el.querySelector('[data-bind="scrubber"]').value = "0";
    this.el.querySelector(".media-art-img").hidden = true;
    this.el.querySelector(".media-art-placeholder").hidden = false;
    this._currentToken = null;
  }

  _tick() {
    const d = this._lastUpdate;
    if (!d || !d.active || this._scrubbing) return;
    let pos = d.position_us;
    if (d.playback_status === "Playing" && d.position_ts) {
      const elapsed = Date.now() / 1000 - d.position_ts;
      pos += elapsed * d.rate * US_PER_S;
    }
    if (d.length_us > 0) {
      pos = Math.min(pos, d.length_us);
    }
    this.el.querySelector('[data-bind="position"]').textContent = fmtTime(pos);
    this.el.querySelector('[data-bind="length"]').textContent = fmtTime(d.length_us);
    if (d.length_us > 0) {
      const fraction = Math.max(0, Math.min(1, pos / d.length_us));
      this.el.querySelector('[data-bind="scrubber"]').value =
        String(Math.round(fraction * 1000));
    }
  }

  _onAction(action) {
    if (action === "shuffle") return this._sendShuffle();
    if (action === "loop") return this._sendLoop();
    return this._send(action);
  }

  async _send(action) {
    try {
      await fetch(`/api/media/${encodeURIComponent(action)}`, { method: "POST" });
    } catch (err) {
      console.error(`[media] action '${action}' failed:`, err);
    }
  }

  async _sendShuffle() {
    const desired = !(this._lastUpdate?.shuffle);
    try {
      await fetch("/api/media/shuffle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: desired }),
      });
    } catch (err) {
      console.error("[media] shuffle failed:", err);
    }
  }

  async _sendLoop() {
    // Cycle: None -> Track -> Playlist -> None (matches MPRIS spec)
    const cycle = { None: "Track", Track: "Playlist", Playlist: "None" };
    const next = cycle[this._lastUpdate?.loop_status] || "Track";
    try {
      await fetch("/api/media/loop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
    } catch (err) {
      console.error("[media] loop failed:", err);
    }
  }

  async _sendSeek(fraction) {
    const d = this._lastUpdate;
    if (!d || !d.length_us) return;
    const pos = Math.round(fraction * d.length_us);
    try {
      await fetch("/api/media/set_position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ position_us: pos }),
      });
    } catch (err) {
      console.error("[media] seek failed:", err);
    }
  }

  destroy() {
    clearInterval(this._timer);
  }
}

registerWidget("media", MediaWidget);
