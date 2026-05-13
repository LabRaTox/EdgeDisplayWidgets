// YouTube widget: thumbnail grid of configured videos/playlists.
// Tap on a tile opens a fullscreen overlay with a youtube-nocookie embed;
// MPRIS playback (if any) is paused for the duration and resumed on close.

import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function thumbUrl(entry) {
  if (entry.thumbnail) return entry.thumbnail;
  if (entry.kind === "video") return `https://i.ytimg.com/vi/${entry.id}/hqdefault.jpg`;
  return "";
}

class YoutubeWidget {
  static modules = ["youtube"];

  mount(el) {
    this.el = el;
    el.classList.add("youtube-widget");
    el.innerHTML = `
      <h3>YouTube</h3>
      <div class="yt-grid" data-bind="grid">
        <div class="yt-empty">…</div>
      </div>
    `;
    this._lastKey = "";
  }

  update(data) {
    const grid = this.el.querySelector('[data-bind="grid"]');
    const entries = data?.entries || [];
    if (entries.length === 0) {
      grid.innerHTML = `<div class="yt-empty">${t("widget.youtube.empty")}</div>`;
      this._lastKey = "";
      return;
    }
    const key = entries.map((e) => `${e.kind}:${e.id}`).join("|");
    if (key === this._lastKey) return;
    this._lastKey = key;

    grid.innerHTML = "";
    for (const entry of entries) {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "yt-tile";
      tile.dataset.kind = entry.kind;
      tile.dataset.id = entry.id;
      const thumb = thumbUrl(entry);
      tile.innerHTML = `
        ${
          thumb
            ? `<img class="yt-thumb" src="${thumb}" alt="" loading="lazy" referrerpolicy="no-referrer">`
            : `<div class="yt-thumb yt-thumb-fallback" aria-hidden="true">▶</div>`
        }
        <div class="yt-meta">
          <div class="yt-title">${escapeHtml(entry.title || entry.id)}</div>
          ${
            entry.kind === "playlist"
              ? `<div class="yt-badge">${t("widget.youtube.playlist_badge")}</div>`
              : entry.author
                ? `<div class="yt-author">${escapeHtml(entry.author)}</div>`
                : ""
          }
        </div>
      `;
      tile.addEventListener("click", () => openOverlay(entry));
      grid.appendChild(tile);
    }
  }

  destroy() {}
}

// ---------------------------------------------------------- fullscreen overlay

let _overlay = null;
let _wasPlaying = false;

function ensureOverlay() {
  if (_overlay) return _overlay;
  const root = document.createElement("div");
  root.id = "yt-overlay";
  root.hidden = true;
  root.innerHTML = `
    <div class="yt-overlay-backdrop"></div>
    <div class="yt-overlay-panel" role="dialog" aria-label="${t("widget.youtube.dialog_label")}">
      <button type="button" class="yt-overlay-close" aria-label="${t("common.close")}">×</button>
      <div class="yt-overlay-frame" data-bind="frame"></div>
    </div>
  `;
  document.body.appendChild(root);
  root.querySelector(".yt-overlay-close").addEventListener("click", closeOverlay);
  root.querySelector(".yt-overlay-backdrop").addEventListener("click", closeOverlay);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !root.hidden) closeOverlay();
  });
  _overlay = root;
  return root;
}

function embedUrl(entry) {
  const params = "autoplay=1&rel=0&modestbranding=1&playsinline=1";
  if (entry.kind === "playlist") {
    return `https://www.youtube-nocookie.com/embed/videoseries?list=${encodeURIComponent(entry.id)}&${params}`;
  }
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(entry.id)}?${params}`;
}

async function openOverlay(entry) {
  const root = ensureOverlay();
  await pauseMprisIfPlaying();
  const frame = root.querySelector('[data-bind="frame"]');
  frame.innerHTML = `<iframe
    src="${embedUrl(entry)}"
    allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
    allowfullscreen
    frameborder="0"></iframe>`;
  root.hidden = false;
  requestAnimationFrame(() => root.classList.add("is-open"));
}

function closeOverlay() {
  if (!_overlay) return;
  _overlay.classList.remove("is-open");
  setTimeout(async () => {
    _overlay.hidden = true;
    // Removing the iframe is what actually stops audio playback in Chromium.
    _overlay.querySelector('[data-bind="frame"]').innerHTML = "";
    if (_wasPlaying) {
      try {
        await fetch("/api/media/play", { method: "POST" });
      } catch (err) {
        console.warn("[youtube] resume MPRIS failed:", err);
      }
      _wasPlaying = false;
    }
  }, 200);
}

async function pauseMprisIfPlaying() {
  try {
    const r = await fetch("/api/snapshot");
    if (!r.ok) return;
    const snap = await r.json();
    const media = snap.media?.data;
    if (media?.active && media?.playback_status === "Playing") {
      _wasPlaying = true;
      await fetch("/api/media/pause", { method: "POST" });
    }
  } catch (err) {
    console.warn("[youtube] pause MPRIS failed:", err);
  }
}

registerWidget("youtube", YoutubeWidget);
