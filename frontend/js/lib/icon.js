// Shared icon rendering for Quick Actions (and anywhere else that stores a
// user-chosen icon string).
//
// An icon string is either:
//   • a Tabler icon, encoded as "ti:<name>" (e.g. "ti:bolt") — rendered from
//     the self-hosted sprite via <use>, inheriting currentColor.
//   • anything else — treated as literal text/emoji and rendered as-is.
//
// Keeping this in one module means the live widget and the settings editor
// render icons identically. The backend stores the raw string untouched.

export const TABLER_PREFIX = "ti:";
export const APP_ICON_PREFIX = "app:";
export const TABLER_SPRITE_URL = "/vendor/tabler/tabler-sprite.svg";

// Desktop-app icon names (file stems) served by /api/apps/icon/<name>.
const SAFE_APP_NAME = /^[A-Za-z0-9._+-]+$/;

// Tabler icon names are lowercase kebab-case + digits. Enforce that before we
// interpolate the name into a sprite fragment id, so a crafted icon string in
// config can never break out of the href.
const SAFE_NAME = /^[a-z0-9-]+$/;

export function isTablerIcon(icon) {
  return typeof icon === "string" && icon.startsWith(TABLER_PREFIX);
}

export function tablerName(icon) {
  return isTablerIcon(icon) ? icon.slice(TABLER_PREFIX.length) : "";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

/**
 * Build the HTML for an icon string.
 *
 * @param {string} icon       the stored icon string ("ti:name" or emoji/text)
 * @param {object} [opts]
 * @param {string} [opts.fallback]  HTML shown when `icon` is empty (default "")
 * @param {string} [opts.svgClass]  extra class(es) on the generated <svg>
 * @returns {string} HTML safe to assign to innerHTML
 */
export function iconMarkup(icon, { fallback = "", svgClass = "" } = {}) {
  if (typeof icon === "string" && icon.startsWith(APP_ICON_PREFIX)) {
    const name = icon.slice(APP_ICON_PREFIX.length);
    if (SAFE_APP_NAME.test(name)) {
      const cls = svgClass ? `qa-appimg ${svgClass}` : "qa-appimg";
      return `<img class="${cls}" src="/api/apps/icon/${name}" alt="" aria-hidden="true">`;
    }
    return fallback;
  }
  if (isTablerIcon(icon)) {
    const name = tablerName(icon);
    if (SAFE_NAME.test(name)) {
      const cls = svgClass ? `ti-svg ${svgClass}` : "ti-svg";
      return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><use href="${TABLER_SPRITE_URL}#tabler-${name}"></use></svg>`;
    }
    return fallback; // unknown/garbled tabler name → fallback
  }
  const text = String(icon ?? "");
  return text ? escapeHtml(text) : fallback;
}
