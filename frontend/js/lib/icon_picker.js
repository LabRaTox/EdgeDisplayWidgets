// Shared icon picker — a tabbed popover (Tabler sprite + emoji-picker-element),
// both self-hosted under /vendor/. Used by the settings editor and the
// in-widget tile editor so icon selection is identical everywhere.
//
// openIconPicker(target, currentIcon) returns a Promise<string|null>:
//   "ti:<name>" -> a chosen Tabler icon
//   "<emoji>"   -> a chosen emoji
//   ""          -> clear the icon
//   null        -> cancelled, leave the icon untouched

import { t } from "../i18n.js";
import { iconMarkup, loadTablerIndex } from "./icon.js";

const EMOJI_PICKER_URL = "/vendor/emoji-picker-element/picker.js";
const EMOJI_DATA_URL = "/vendor/emoji-picker-element/data.json";

const TABLER_MAX_RESULTS = 300;
// Shown when the search box is empty. Filtered against the loaded index so a
// name missing from the vendored sprite never renders as a broken icon.
const TABLER_COMMON = [
  "bolt", "power", "refresh", "reload", "bell", "bell-off", "bulb", "lock",
  "lock-open", "settings", "home", "sun", "moon", "temperature", "droplet",
  "wind", "cloud", "snowflake", "flame", "coffee", "music", "volume",
  "volume-off", "player-play", "player-pause", "player-stop", "plug",
  "plug-connected", "wifi", "bluetooth", "camera", "video", "photo",
  "download", "upload", "trash", "device-desktop", "device-tv",
  "device-laptop", "server", "terminal-2", "rocket", "alarm", "clock",
  "calendar", "mail", "message", "phone", "star", "heart", "eye", "eye-off",
  "battery", "broadcast", "world", "link", "key", "shield", "robot", "bug",
  "code", "bookmark", "flag", "map-pin", "car", "plane", "bed", "door",
  "fan", "air-conditioning",
];

function escapeAttr(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

let _emojiLoadPromise = null;
function loadEmojiPickerElement() {
  if (window.customElements?.get("emoji-picker")) return Promise.resolve(true);
  if (!_emojiLoadPromise) {
    _emojiLoadPromise = import(EMOJI_PICKER_URL)
      .then(() => true)
      .catch((err) => {
        console.warn("[icon-picker] emoji-picker failed to load:", err);
        _emojiLoadPromise = null; // allow retry on next open
        return false;
      });
  }
  return _emojiLoadPromise;
}

export async function openIconPicker(target, currentIcon = "") {
  return new Promise((resolve) => {
    const popover = document.createElement("div");
    popover.className = "qa-icon-popover";
    const startTab = currentIcon && !currentIcon.startsWith("ti:") ? "emoji" : "tabler";
    popover.innerHTML = `
      <div class="qa-icon-toolbar">
        <div class="qa-icon-tabs">
          <button type="button" class="qa-icon-tab${startTab === "tabler" ? " is-active" : ""}" data-tab="tabler">${t("qa_editor.icon_tab_tabler")}</button>
          <button type="button" class="qa-icon-tab${startTab === "emoji" ? " is-active" : ""}" data-tab="emoji">${t("qa_editor.icon_tab_emoji")}</button>
        </div>
        <span class="qa-icon-spacer"></span>
        <button type="button" class="btn" data-act="clear">${t("qa_editor.icon_none")}</button>
        <button type="button" class="btn" data-act="cancel">${t("common.cancel")}</button>
      </div>
      <div class="qa-icon-pane" data-pane="tabler"${startTab === "tabler" ? "" : " hidden"}>
        <input type="search" class="qa-icon-search" placeholder="${t("qa_editor.icon_search")}" autocomplete="off">
        <div class="qa-icon-grid" data-bind="grid"></div>
        <div class="qa-icon-status" data-bind="status"></div>
      </div>
      <div class="qa-icon-pane" data-pane="emoji"${startTab === "emoji" ? "" : " hidden"}></div>
    `;
    document.body.appendChild(popover);

    const grid = popover.querySelector('[data-bind="grid"]');
    const status = popover.querySelector('[data-bind="status"]');
    const searchInput = popover.querySelector(".qa-icon-search");
    const emojiPane = popover.querySelector('[data-pane="emoji"]');

    const place = () => {
      const r = target.getBoundingClientRect();
      const pr = popover.getBoundingClientRect();
      let top = r.bottom + 6;
      let left = r.left;
      if (top + pr.height > window.innerHeight - 8) {
        top = Math.max(8, r.top - pr.height - 6);
      }
      if (left + pr.width > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - pr.width - 8);
      }
      popover.style.top = `${top}px`;
      popover.style.left = `${left}px`;
    };

    let resolved = false;
    const close = (value) => {
      if (resolved) return;
      resolved = true;
      popover.remove();
      document.removeEventListener("pointerdown", onDocPointer, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      resolve(value);
    };
    const onDocPointer = (e) => {
      if (popover.contains(e.target) || target.contains(e.target)) return;
      close(null);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close(null);
    };

    // ---- Tabler tab ----
    let tablerIndex = null; // [{n, k}]
    const renderTabler = (query) => {
      if (!tablerIndex) return;
      const q = query.trim().toLowerCase();
      let matches;
      if (!q) {
        const present = new Set(tablerIndex.map((i) => i.n));
        matches = TABLER_COMMON.filter((n) => present.has(n)).map((n) => ({ n }));
      } else {
        matches = [];
        for (const item of tablerIndex) {
          if (item.k.includes(q)) {
            matches.push(item);
            if (matches.length >= TABLER_MAX_RESULTS) break;
          }
        }
      }
      grid.innerHTML = matches
        .map(
          (m) =>
            `<button type="button" class="qa-icon-cell" data-name="${escapeAttr(m.n)}" title="${escapeAttr(m.n)}">${iconMarkup(`ti:${m.n}`)}</button>`,
        )
        .join("");
      status.textContent = matches.length
        ? (q ? t("qa_editor.icon_results", { count: matches.length }) : "")
        : t("qa_editor.icon_no_results");
      place();
    };

    loadTablerIndex()
      .then((idx) => {
        tablerIndex = idx;
        renderTabler(searchInput.value);
      })
      .catch((err) => {
        console.error("[icon-picker] tabler index failed:", err);
        status.textContent = t("qa_editor.icon_load_error");
      });

    let searchTimer = null;
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => renderTabler(searchInput.value), 120);
    });
    grid.addEventListener("click", (e) => {
      const cell = e.target.closest(".qa-icon-cell");
      if (cell) close(`ti:${cell.dataset.name}`);
    });

    // ---- Emoji tab (lazy mounted on first activation) ----
    let emojiMounted = false;
    const mountEmoji = async () => {
      if (emojiMounted) return;
      emojiMounted = true;
      const ok = await loadEmojiPickerElement();
      if (!ok) {
        emojiPane.innerHTML = `<div class="qa-icon-fallback">
          <p>${t("qa_editor.icon_emoji_unavailable")}</p>
          <input type="text" class="qa-icon-emoji-manual" value="${escapeAttr(currentIcon.startsWith("ti:") ? "" : currentIcon)}">
          <button type="button" class="btn btn-primary" data-act="emoji-ok">${t("common.save")}</button>
        </div>`;
        emojiPane.querySelector('[data-act="emoji-ok"]').addEventListener("click", () => {
          close(emojiPane.querySelector(".qa-icon-emoji-manual").value);
        });
        place();
        return;
      }
      const picker = document.createElement("emoji-picker");
      picker.className = "dark";
      picker.dataset.source = EMOJI_DATA_URL;
      picker.addEventListener("emoji-click", (e) => close(e.detail.unicode || ""));
      emojiPane.appendChild(picker);
      place();
    };
    if (startTab === "emoji") mountEmoji();

    // ---- Tab switching + toolbar ----
    popover.querySelector(".qa-icon-tabs").addEventListener("click", (e) => {
      const btn = e.target.closest(".qa-icon-tab");
      if (!btn) return;
      const tab = btn.dataset.tab;
      for (const b of popover.querySelectorAll(".qa-icon-tab")) {
        b.classList.toggle("is-active", b === btn);
      }
      for (const pane of popover.querySelectorAll(".qa-icon-pane")) {
        pane.hidden = pane.dataset.pane !== tab;
      }
      if (tab === "emoji") mountEmoji();
      if (tab === "tabler") searchInput.focus();
      place();
    });
    popover.querySelector('[data-act="clear"]').addEventListener("click", () => close(""));
    popover.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));

    requestAnimationFrame(() => {
      place();
      if (startTab === "tabler") searchInput.focus();
    });
    window.addEventListener("resize", place);
    // Defer so the click that opened us doesn't immediately close us.
    setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointer, true);
      document.addEventListener("keydown", onKey);
    }, 0);
  });
}
