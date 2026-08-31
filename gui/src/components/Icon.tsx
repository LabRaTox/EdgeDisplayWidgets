import { useEffect, useState } from "react";

import {
  appIconUrl,
  isAppIcon,
  isSafeTablerName,
  isTablerIcon,
  loadTablerSprite,
  tablerName,
} from "../lib/icons";

/**
 * One stored icon string, rendered the way the kiosk renders it.
 *
 * Tabler icons need the sprite in the document, which is fetched on first
 * use. Until it arrives the icon renders as nothing rather than as a broken
 * shape, and a name that is not a Tabler name falls back to the raw text, so
 * a hand-edited config never produces an empty tile with no explanation.
 */
export function Icon({ icon, className }: { icon: string; className?: string }) {
  const wantsSprite = isTablerIcon(icon);
  const [spriteReady, setSpriteReady] = useState(false);

  useEffect(() => {
    if (!wantsSprite) return;
    let cancelled = false;
    loadTablerSprite()
      .then(() => {
        if (!cancelled) setSpriteReady(true);
      })
      .catch(() => {
        /* no backend, nothing to draw */
      });
    return () => {
      cancelled = true;
    };
  }, [wantsSprite]);

  if (!icon) return null;

  if (wantsSprite) {
    const name = tablerName(icon);
    if (!isSafeTablerName(name)) return <span className={className}>{icon}</span>;
    if (!spriteReady) return <svg className={`ti-svg ${className ?? ""}`} viewBox="0 0 24 24" />;
    return (
      <svg className={`ti-svg ${className ?? ""}`} viewBox="0 0 24 24" aria-hidden="true">
        <use href={`#tabler-${name}`} />
      </svg>
    );
  }

  if (isAppIcon(icon)) {
    return <img className={`app-icon ${className ?? ""}`} src={appIconUrl(icon)} alt="" />;
  }

  return <span className={className}>{icon}</span>;
}
