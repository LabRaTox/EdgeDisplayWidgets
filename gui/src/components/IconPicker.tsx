import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  EMOJI_DATA_URL,
  TABLER_PREFIX,
  type TablerIcon,
  loadTablerIndex,
  loadTablerSprite,
} from "../lib/icons";
import { Icon } from "./Icon";

/** Shown before anything is typed: the icons a dashboard button actually uses. */
const COMMON = [
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

/** A search can match thousands of the ~5900 icons; the grid shows this many. */
const MAX_RESULTS = 300;

/**
 * Picks the icon for a quick action: a Tabler icon or an emoji.
 *
 * Both are stored in the same field, told apart by the `ti:` prefix, which is
 * what the kiosk expects (see frontend/js/lib/icon.js). Anything typed by
 * hand stays untouched, so an icon set in the YAML survives a visit here.
 */
export function IconPicker({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (icon: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"tabler" | "emoji">(
    value && !value.startsWith(TABLER_PREFIX) ? "emoji" : "tabler",
  );
  const ref = useRef<HTMLDivElement>(null);

  /**
   * Keep the popover inside the window.
   *
   * It hangs off the icon field, which sits well down the right-hand column,
   * so on anything but a maximised window it would otherwise run off the
   * bottom and the right edge. Measured and clamped rather than solved in
   * CSS: anchor positioning is not in this WebKit, and a fixed offset would
   * be wrong for whichever window size it was not tuned to.
   */
  const place = useCallback(() => {
    const popover = ref.current;
    const anchor = popover?.parentElement;
    if (!popover || !anchor) return;
    const box = anchor.getBoundingClientRect();
    const margin = 8;
    const width = popover.offsetWidth;
    const height = popover.offsetHeight;

    let left = box.left;
    if (left + width > window.innerWidth - margin) left = window.innerWidth - width - margin;
    if (left < margin) left = margin;

    let top = box.bottom + 6;
    if (top + height > window.innerHeight - margin) {
      // Flip above the field when there is room there, otherwise sit as low
      // as it fits: the popover scrolls internally, so it is never cut off.
      const above = box.top - height - 6;
      top = above >= margin ? above : Math.max(margin, window.innerHeight - height - margin);
    }

    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;
  }, []);

  useLayoutEffect(() => {
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [place]);

  // The tabs are different heights, and the emoji picker only reaches its own
  // once its module has loaded, so re-place on both.
  useLayoutEffect(place, [place, tab]);

  // Stable, because EmojiTab tears its picker down and builds a new one
  // whenever this changes. Inline, that happened on every render of this
  // component, and rebuilding means opening the emoji database again.
  const pickEmoji = useCallback(
    (emoji: string) => {
      onChange(emoji);
      onClose();
    },
    [onChange, onClose],
  );

  // Click outside or Escape closes, like the menus in the top bar.
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div className="icon-popover" ref={ref}>
      <div className="icon-tabs">
        <button
          type="button"
          className={tab === "tabler" ? "active" : ""}
          onClick={() => setTab("tabler")}
        >
          {t("icons.tab_symbols")}
        </button>
        <button
          type="button"
          className={tab === "emoji" ? "active" : ""}
          onClick={() => setTab("emoji")}
        >
          {t("icons.tab_emoji")}
        </button>
        <div className="spacer" />
        <button
          type="button"
          className="btn small ghost"
          onClick={() => {
            onChange("");
            onClose();
          }}
        >
          {t("icons.clear")}
        </button>
      </div>

      {tab === "tabler" ? (
        <TablerTab
          value={value}
          onPick={(name) => {
            onChange(TABLER_PREFIX + name);
            onClose();
          }}
        />
      ) : (
        <EmojiTab onReady={place} onPick={pickEmoji} />
      )}
    </div>
  );
}

function TablerTab({ value, onPick }: { value: string; onPick: (name: string) => void }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState<TablerIcon[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // The sprite is what makes the grid visible at all, the index is what
    // makes it searchable. Both come from the backend, so one failure means
    // the same thing for both.
    Promise.all([loadTablerIndex(), loadTablerSprite()])
      .then(([icons]) => {
        if (!cancelled) setIndex(icons);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const results = useMemo(() => {
    if (!index) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) {
      // Filter the shortlist against the real index: a name that is not in
      // the vendored sprite would render as an empty square.
      const known = new Set(index.map((entry) => entry.n));
      return COMMON.filter((name) => known.has(name));
    }
    const names: string[] = [];
    for (const entry of index) {
      if (entry.n.includes(needle) || entry.k.includes(needle)) {
        names.push(entry.n);
        if (names.length >= MAX_RESULTS) break;
      }
    }
    return names;
  }, [index, query]);

  const current = value.startsWith(TABLER_PREFIX) ? value.slice(TABLER_PREFIX.length) : "";

  if (failed) return <div className="icon-empty">{t("icons.load_failed")}</div>;

  return (
    <>
      <input
        autoFocus
        className="icon-search"
        placeholder={t("icons.search")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {index === null ? (
        <div className="icon-empty">{t("common.loading")}</div>
      ) : results.length === 0 ? (
        <div className="icon-empty">{t("icons.no_match")}</div>
      ) : (
        <div className="icon-grid">
          {results.map((name) => (
            <button
              key={name}
              type="button"
              className={`icon-cell ${current === name ? "active" : ""}`}
              title={name}
              onClick={() => onPick(name)}
            >
              <Icon icon={TABLER_PREFIX + name} />
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function EmojiTab({
  onPick,
  onReady,
}: {
  onPick: (emoji: string) => void;
  onReady: () => void;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let picker: HTMLElement | null = null;
    let cancelled = false;

    // The element is a web component, so it is created imperatively and its
    // data source is set as a property. The database is served by our own
    // backend; the package would otherwise reach for a CDN, and the kiosk
    // machine has no business needing one to show a smiley.
    import("emoji-picker-element")
      .then(() => {
        if (cancelled || !host.current) return;
        picker = document.createElement("emoji-picker");
        (picker as unknown as { dataSource: string }).dataSource = EMOJI_DATA_URL;
        picker.addEventListener("emoji-click", (event) => {
          const detail = (event as CustomEvent<{ unicode?: string }>).detail;
          if (detail?.unicode) onPick(detail.unicode);
        });
        host.current.appendChild(picker);
        onReady();
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      picker?.remove();
    };
  }, [onPick, onReady]);

  if (failed) return <div className="icon-empty">{t("icons.emoji_failed")}</div>;
  return <div className="emoji-host" ref={host} />;
}
