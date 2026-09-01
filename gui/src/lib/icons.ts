/**
 * Icon strings, as the backend stores them.
 *
 * An icon is one of three things, and the raw string is kept untouched:
 *   "ti:<name>"   a Tabler icon from the self-hosted sprite
 *   "app:<name>"  a desktop application icon, served by /api/apps/icon/<name>
 *   anything else literal text, in practice an emoji
 *
 * The kiosk resolves the same three forms in `Bridge.iconUrl`. The two
 * cannot share code, one being Python in the kiosk process and the other
 * bundled into this window, so they share the format instead.
 *
 * The sprite is fetched and injected into this document rather than
 * referenced by URL: `<use href="http://…#id">` only resolves same-origin,
 * and this window is served from tauri://localhost while the sprite lives on
 * the backend.
 */

import { API_BASE } from "../api/client";

export const TABLER_PREFIX = "ti:";
export const APP_ICON_PREFIX = "app:";

const SPRITE_URL = `${API_BASE}/vendor/tabler/tabler-sprite.svg`;
const INDEX_URL = `${API_BASE}/vendor/tabler/icons-index.json`;
const SPRITE_HOST_ID = "tabler-sprite-host";

/** Tabler names are lowercase kebab-case; anything else is not one of ours. */
const SAFE_NAME = /^[a-z0-9-]+$/;

export interface TablerIcon {
  /** name */
  n: string;
  /** space-separated search keywords */
  k: string;
}

export function isTablerIcon(icon: string): boolean {
  return icon.startsWith(TABLER_PREFIX);
}

export function tablerName(icon: string): string {
  return isTablerIcon(icon) ? icon.slice(TABLER_PREFIX.length) : "";
}

export function isAppIcon(icon: string): boolean {
  return icon.startsWith(APP_ICON_PREFIX);
}

export function appIconUrl(icon: string): string {
  return `${API_BASE}/api/apps/icon/${encodeURIComponent(icon.slice(APP_ICON_PREFIX.length))}`;
}

export function isSafeTablerName(name: string): boolean {
  return SAFE_NAME.test(name);
}

// -- the sprite ------------------------------------------------------------

let spritePromise: Promise<boolean> | null = null;

/**
 * Put the sprite into the document once, so `<use href="#tabler-x">` works.
 *
 * About 1.8 MB over loopback, fetched the first time an icon is rendered.
 * Failures are not cached: without a backend there is nothing to draw, and
 * the next attempt should try again rather than stay broken for the session.
 */
export function loadTablerSprite(): Promise<boolean> {
  if (!spritePromise) {
    spritePromise = fetch(SPRITE_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((markup) => {
        if (document.getElementById(SPRITE_HOST_ID)) return true;
        const host = document.createElement("div");
        host.id = SPRITE_HOST_ID;
        // Not `display: none`: Safari and WebKit refuse to resolve <use>
        // into a hidden subtree. Zero-sized and clipped keeps it referenced
        // while taking no space and staying out of the accessibility tree.
        host.setAttribute("aria-hidden", "true");
        host.style.cssText =
          "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none";
        host.innerHTML = markup;
        document.body.appendChild(host);
        return true;
      })
      .catch((error) => {
        spritePromise = null;
        throw error;
      });
  }
  return spritePromise;
}

// -- the search index ------------------------------------------------------

let indexPromise: Promise<TablerIcon[]> | null = null;

/** The compact search index: `[{ n: name, k: keywords }, …]`, cached. */
export function loadTablerIndex(): Promise<TablerIcon[]> {
  if (!indexPromise) {
    indexPromise = fetch(INDEX_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((body: { icons?: TablerIcon[] }) =>
        Array.isArray(body?.icons) ? body.icons : [],
      )
      .catch((error) => {
        indexPromise = null;
        throw error;
      });
  }
  return indexPromise;
}

/** Emoji database for the picker, served by the backend rather than a CDN. */
export const EMOJI_DATA_URL = `${API_BASE}/vendor/emoji-picker-element/data.json`;
