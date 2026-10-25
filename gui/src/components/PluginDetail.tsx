import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, images, openExternal } from "../api/client";
import { pick } from "../lib/localized";
import type { StoreEntry, StoreUser, StoreWarning, ThemeMeta, WidgetMeta } from "../types";
import { Icon } from "./Icon";
import { Rating } from "./Rating";
import { ThemeSwatch, themeLabel } from "./ThemeView";

/** What the store's review found, shown before installing and on the detail page. */
export function Warnings({ warnings }: { warnings: StoreWarning[] }) {
  const { t } = useTranslation();
  if (warnings.length === 0) return null;
  return (
    <div className="hint warn">
      <div>{t("widgets.warnings", { count: warnings.length })}</div>
      <ul className="store-warnings">
        {warnings.map((w, i) => (
          <li key={i}>
            <span className="code">{t(`widgets.finding.${w.kind}`, w.kind)}</span> {w.value}{" "}
            <span className="muted">
              ({w.file}
              {w.line ? `:${w.line}` : ""})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The rows of the facts table, in the order they stand. Empty ones are left out. */
type Facts = {
  type?: string | null;
  category?: string | null;
  version?: string | null;
  author?: string | null;
  license?: string | null;
  downloads?: string | null;
  released?: string | null;
  size?: string | null;
  minApp?: string | null;
  modules?: string | null;
  source?: string | null;
  support?: string | null;
};

const ORDER: (keyof Omit<Facts, "support">)[] = [
  "type", "category", "version", "author", "license", "downloads", "released", "size",
  "minApp", "modules", "source",
];

/**
 * The facts on the right, as a table and not as running text: one looks for
 * a single value in it ("which modules does it need?"), and a list with
 * fixed rows is faster to read for that than a paragraph.
 */
function FactsTable({ facts }: { facts: Facts }) {
  const { t } = useTranslation();
  return (
    <dl>
      {ORDER.filter((key) => facts[key]).map((key) => (
        <div key={key} className="detail-row">
          <dt>{t(`detail.${key}`)}</dt>
          <dd>{facts[key]}</dd>
        </div>
      ))}
      {facts.support && (
        <div className="detail-row">
          <dt>{t("detail.support")}</dt>
          <dd>
            <button type="button" className="linkish" onClick={() => void openExternal(facts.support!)}>
              {t("detail.open_support")}
            </button>
          </dd>
        </div>
      )}
    </dl>
  );
}

/** One large picture and, when there is more than one, a row to switch. */
function Gallery({ count, src }: { count: number; src: (index: number) => string }) {
  const [shown, setShown] = useState(0);
  if (count === 0) return null;
  return (
    <div className="detail-pictures">
      <img className="detail-picture-large" src={src(Math.min(shown, count - 1))} alt="" />
      {count > 1 && (
        <div className="detail-picture-row">
          {Array.from({ length: count }, (_, i) => (
            <button
              key={i}
              type="button"
              className={i === shown ? "detail-picture-small active" : "detail-picture-small"}
              onClick={() => setShown(i)}
            >
              <img src={src(i)} alt="" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  return (
    <button type="button" className="btn small detail-back" onClick={onBack}>
      ‹ {t("detail.back")}
    </button>
  );
}

function DetailIcon({
  src,
  name,
  accent,
  symbol,
}: {
  src: string;
  name: string;
  accent?: string;
  /** A Tabler name, as on the card; built-in widgets have one. */
  symbol?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (src && !failed) {
    return <img className="detail-icon" src={src} alt="" onError={() => setFailed(true)} />;
  }
  return (
    <span className="detail-icon placeholder" style={accent ? { background: accent } : undefined}>
      {symbol ? <Icon icon={symbol} /> : name.slice(0, 1)}
    </span>
  );
}

/**
 * The detail page of a widget or design that is here: built in or installed.
 *
 * It takes the place of the card list instead of lying over it as a dialog:
 * pictures, description and facts need the full width, and a dialog one
 * has to close first stands in the way. The way back is at the top.
 */
export function InstalledDetail({
  id,
  kind,
  meta,
  storeEntry,
  user,
  onBack,
}: {
  user: StoreUser | null;
  id: string;
  kind: "widget" | "theme";
  meta: WidgetMeta | ThemeMeta;
  /** The same plugin in the catalog, if it is there: downloads and date. */
  storeEntry: StoreEntry | null;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const name = kind === "theme" ? themeLabel(id, meta.name) : pick(meta.name, id);
  const description = pick(meta.description) || pick(meta.summary);
  const changelog = pick(meta.changelog);
  const widget = kind === "widget" ? (meta as WidgetMeta) : null;
  // Size, date and minimum version only the store knows, and only for the
  // version that is installed; otherwise they would describe another one.
  const same = storeEntry?.latest.version === meta.version ? storeEntry.latest : null;

  const facts: Facts = {
    type: t(`widgets.type.${kind}`),
    category: widget ? t(`widgets.category.${widget.category}`, widget.category) : null,
    version: meta.version,
    author: meta.author || null,
    license: meta.license || null,
    downloads: storeEntry ? String(storeEntry.latest.downloads) : null,
    released: same ? new Date(same.released_at).toLocaleDateString() : null,
    size: same ? `${Math.max(1, Math.round(same.size / 1024))} KB` : null,
    minApp: same?.min_app_version ?? null,
    modules: widget ? widget.modules.join(", ") || t("widgets.no_module") : null,
    source: t(meta.builtin ? "widgets.builtin" : meta.source === "local" ? "widgets.local" : "detail.from_store"),
    support: meta.support || null,
  };

  const iconUrl = meta.builtin ? "" : meta.icon_url ? images.pluginIcon(id, meta.version) : "";

  return (
    <div className="plugin-detail">
      <BackButton onBack={onBack} />

      <header className="detail-head">
        {kind === "theme" ? (
          <ThemeSwatch name={id} className="theme-swatch detail-swatch" />
        ) : (
          <DetailIcon src={iconUrl} name={name} accent={widget?.accent} symbol={widget?.symbol} />
        )}
        <div>
          <small className="detail-category">{facts.category ?? facts.type}</small>
          <h2 className={meta.builtin && kind === "theme" ? "capitalize" : undefined}>{name}</h2>
          {meta.author && (
            <small className="detail-author">{t("widgets.by_author", { author: meta.author })}</small>
          )}
        </div>
      </header>

      <div className="detail-columns">
        <div className="detail-main">
          <Gallery
            count={meta.builtin ? 0 : meta.screenshots}
            src={(i) => images.pluginScreenshot(id, i, meta.version)}
          />
          <h3>{t("detail.overview")}</h3>
          <p className="detail-text">{description || t("detail.no_description")}</p>
          {widget?.warnings && widget.warnings.length > 0 && <Warnings warnings={widget.warnings} />}
          {changelog && (
            <>
              <h3>{t("detail.whats_new")}</h3>
              <p className="detail-text">{changelog}</p>
            </>
          )}
        </div>

        <aside className="detail-facts">
          <h3>{t("detail.facts")}</h3>
          <FactsTable facts={facts} />
          {/* Only for what is in the store: the rating lives there. */}
          {storeEntry && <Rating slug={storeEntry.slug} user={user} />}
        </aside>
      </div>
    </div>
  );
}

/**
 * The detail page of a plugin that is only in the store.
 *
 * Built like the one of an installed plugin, the same arrangement and the
 * same classes: one should not have to find out where one has landed just
 * because the plugin is not on the machine yet. What it adds only the store
 * has: the versions, the findings of the review and the button to get it.
 *
 * Loaded here and not for the list: the catalog brings only the newest
 * version per plugin, everything else costs a round over the network that
 * is worth it only for the one someone looks at.
 */
export function StoreDetail({
  slug,
  known,
  busy,
  user,
  onInstall,
  onBack,
}: {
  user: StoreUser | null;
  slug: string;
  /** What the list already had, so something stands there at once. */
  known: StoreEntry | null;
  busy: boolean;
  onInstall: (entry: StoreEntry) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [entry, setEntry] = useState<StoreEntry | null>(known);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .storePlugin(slug)
      // The detail answer lacks what the backend adds to the catalog.
      .then((detail) => !cancelled && setEntry({ ...known, ...detail } as StoreEntry))
      .catch((exc: unknown) => !cancelled && setError(exc instanceof Error ? exc.message : String(exc)));
    return () => {
      cancelled = true;
    };
  }, [slug, known]);

  if (!entry) {
    return (
      <div className="plugin-detail">
        <BackButton onBack={onBack} />
        {error ? <p className="error-note">{error}</p> : <p className="hint">{t("common.loading")}</p>}
      </div>
    );
  }

  const latest = entry.latest;
  const name = pick(entry.i18n?.name, entry.name);
  const description = pick(entry.i18n?.description) || entry.description || pick(entry.i18n?.summary, entry.summary);
  const changelog = pick(latest.changelog_i18n) || latest.changelog || "";
  const versions = entry.versions ?? [];
  const kind = entry.kind === "theme" ? "theme" : "widget";

  const facts: Facts = {
    type: t(`widgets.type.${kind}`),
    category: kind === "widget" ? t(`widgets.category.${entry.category}`, entry.category) : null,
    version: latest.version,
    author: entry.author,
    license: entry.license,
    downloads: String(latest.downloads),
    released: new Date(latest.released_at).toLocaleDateString(),
    size: `${Math.max(1, Math.round(latest.size / 1024))} KB`,
    minApp: latest.min_app_version,
    source: t("detail.from_store"),
    // The store files the manifest's `support` as `source_url`.
    support: entry.source_url,
  };

  return (
    <div className="plugin-detail">
      <BackButton onBack={onBack} />

      <header className="detail-head">
        <DetailIcon src={latest.icon_url ? images.storeIcon(entry.slug, latest.version) : ""} name={name} />
        <div>
          <small className="detail-category">{facts.category ?? facts.type}</small>
          <h2>{name}</h2>
          <small className="detail-author">{t("widgets.by_author", { author: entry.author })}</small>
        </div>
        <div className="detail-head-buttons">
          <button
            type="button"
            className="btn primary"
            disabled={busy || !entry.compatible}
            onClick={() => onInstall(entry)}
          >
            {busy ? t("widgets.installing") : t("widgets.install")}
          </button>
        </div>
      </header>

      {error && <p className="error-note">{error}</p>}
      {!entry.compatible && (
        <p className="error-note">{t("widgets.needs_version", { version: latest.min_app_version })}</p>
      )}

      <div className="detail-columns">
        <div className="detail-main">
          <Gallery
            count={latest.screenshot_urls?.length ?? 0}
            src={(i) => images.storeScreenshot(entry.slug, latest.version, i)}
          />
          <h3>{t("detail.overview")}</h3>
          <p className="detail-text">{description || t("detail.no_description")}</p>

          {/* Before installing, not after: what a plugin does one should know
              before it is on the machine. */}
          {latest.warnings.length > 0 && <Warnings warnings={latest.warnings} />}

          {changelog && (
            <>
              <h3>{t("detail.whats_new")}</h3>
              <p className="detail-text">{changelog}</p>
            </>
          )}

          {versions.length > 1 && (
            <>
              <h3>{t("detail.versions")}</h3>
              <ul className="detail-versions">
                {versions.map((v) => (
                  <li key={v.version}>
                    <strong>{v.version}</strong>
                    <span className="hint">
                      {new Date(v.released_at).toLocaleDateString()} · {v.downloads} ×
                      {/* Withdrawn means: out of the catalog, but whoever has
                          it keeps it. That belongs here. */}
                      {v.state && v.state !== "approved" ? ` · ${t(`submit.status.${v.state}`)}` : ""}
                    </span>
                    {v.note && <span className="hint"> · {v.note}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <aside className="detail-facts">
          <h3>{t("detail.facts")}</h3>
          <FactsTable facts={facts} />
          <Rating slug={entry.slug} user={user} />
        </aside>
      </div>
    </div>
  );
}
