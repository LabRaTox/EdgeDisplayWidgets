import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { API_BASE, ApiError, api, images, openExternal } from "../api/client";
import i18n, { loadDashboardStrings } from "../i18n";
import { useStore } from "../store";
import type {
  DeviceStart,
  ModuleSettings,
  StoreEntry,
  StorePending,
  StoreUser,
  ThemeMeta,
  WidgetMeta,
} from "../types";
import { pick } from "../lib/localized";
import { Field, applies, readPath, writePath } from "./Field";
import { Icon } from "./Icon";
import { Modal } from "./Modal";
import { InstalledDetail, StoreDetail, Warnings } from "./PluginDetail";
import { StoreSubmit } from "./StoreSubmit";
import { ThemeSwatch, themeLabel } from "./ThemeView";

/**
 * The topics on the left, in menu order. Empty ones stay in the list, dimmed:
 * they show what there can be without leading to an empty page. `other`
 * comes last, where entries without a category end up.
 */
const CATEGORIES = [
  "system",
  "monitoring",
  "media",
  "time",
  "productivity",
  "smarthome",
  "weather",
  "video",
  "other",
] as const;

/** How long a confirmation under the header stays. */
const NOTICE_MS = 5000;

/** The tabs on top: by what a plugin is, not by topic. */
const TYPES = ["widget", "theme"] as const;
type PluginType = (typeof TYPES)[number];

type Entry =
  | { kind: "widget"; id: string; meta: WidgetMeta }
  | { kind: "theme"; id: string; meta: ThemeMeta }
  | { kind: "store"; id: string; entry: StoreEntry };

function message(exc: unknown): string {
  return exc instanceof ApiError || exc instanceof Error ? exc.message : String(exc);
}


function categoryOf(entry: Entry): string {
  if (entry.kind === "theme") return "other";
  const raw = entry.kind === "widget" ? entry.meta.category : entry.entry.category;
  return (CATEGORIES as readonly string[]).includes(raw) ? raw : "other";
}

/**
 * After installing or removing, the widget list, the module schemas and the
 * texts all change. The layout editor should offer a new widget without the
 * window being restarted.
 */
async function refreshAfterChange(): Promise<void> {
  await useStore.getState().load();
  await loadDashboardStrings(i18n.language);
}

/**
 * Every widget in one list: the built-in ones, the installed ones, and what
 * the store has that is not installed yet. Whether a widget is already here
 * is a property, not a place, so there is no separate store page.
 *
 * A widget's switch turns its modules on and off, and its settings are the
 * settings of those modules. Some modules feed several widgets (`system`
 * feeds CPU, RAM and network), so their cards switch together; each card
 * names the modules it depends on.
 */
export function WidgetsView() {
  const { t } = useTranslation();
  const widgetMeta = useStore((s) => s.widgetMeta);
  const themes = useStore((s) => s.themes);
  const themeMeta = useStore((s) => s.themeMeta);
  const settings = useStore((s) => s.settings);
  const [type, setType] = useState<PluginType>("widget");
  /** Which plugin is shown whole; `null` is the list. */
  const [detail, setDetail] = useState<{ kind: Entry["kind"]; id: string } | null>(null);

  const [catalog, setCatalog] = useState<StoreEntry[] | null>(null);
  const [storeError, setStoreError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [installOpen, setInstallOpen] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [user, setUser] = useState<StoreUser | null>(null);
  const [pending, setPending] = useState<StorePending | null>(null);

  const fetchCatalog = useCallback(async (): Promise<StoreEntry[]> => {
    try {
      const answer = await api.storeCatalog();
      setCatalog(answer.plugins);
      setStoreError("");
      return answer.plugins;
    } catch (exc) {
      setCatalog([]);
      setStoreError(t("widgets.store_unreachable", { reason: message(exc) }));
      return [];
    }
  }, [t]);

  useEffect(() => {
    void fetchCatalog();
    api
      .storeMe()
      .then(({ user: who }) => setUser(who))
      .catch(() => setUser(null));
  }, [fetchCatalog]);

  // A short confirmation ("Nothing new.", "installed …") goes again after a
  // few seconds; errors are shown elsewhere and stay.
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // Asked again whenever someone signs in or out; only reviewers get counts.
  useEffect(() => {
    if (!user) {
      setPending(null);
      return;
    }
    api
      .storePending()
      .then(({ pending: waiting }) => setPending(waiting))
      .catch(() => setPending(null));
  }, [user]);

  /**
   * One list per type. What is installed already comes once: its own card
   * knows more than the catalog entry.
   */
  const entriesOf = (of: PluginType): Entry[] => {
    const here: Entry[] =
      of === "widget"
        ? Object.entries(widgetMeta).map(([id, meta]) => ({ kind: "widget" as const, id, meta }))
        : themes
            .filter((id) => themeMeta[id])
            .map((id) => ({ kind: "theme" as const, id, meta: themeMeta[id]! }));
    const known = new Set(here.map((e) => e.id));
    const fromStore = (catalog ?? [])
      .filter((s) => (s.kind || "widget") === of && !known.has(s.slug))
      .map((s) => ({ kind: "store" as const, id: s.slug, entry: s }));
    const list = [...here, ...fromStore];
    const sortName = (e: Entry) =>
      e.kind === "store" ? pick(e.entry.i18n?.name, e.entry.name) : pick(e.meta.name, e.id);
    return list.sort((a, b) => sortName(a).localeCompare(sortName(b)));
  };
  const entries = entriesOf(type);

  const counts = new Map<string, number>();
  for (const e of entries) counts.set(categoryOf(e), (counts.get(categoryOf(e)) ?? 0) + 1);
  const installedCount = entries.filter((e) => e.kind !== "store").length;

  const visible =
    filter === "all"
      ? entries
      : filter === "installed"
        ? entries.filter((e) => e.kind !== "store")
        : entries.filter((e) => categoryOf(e) === filter);

  const updates = (catalog ?? []).filter((s) => s.update && s.compatible);

  const install = async (entry: StoreEntry) => {
    setBusy(entry.slug);
    setStoreError("");
    setNotice("");
    try {
      await api.install(entry.slug);
      setNotice(
        t("widgets.installed", {
          name: pick(entry.i18n?.name, entry.name),
          version: entry.latest.version,
        }),
      );
      await refreshAfterChange();
      await fetchCatalog();
    } catch (exc) {
      setStoreError(message(exc));
    } finally {
      setBusy("");
    }
  };

  /** One after the other: each install reloads the hub. */
  const updateAll = async () => {
    setBusy("__all");
    setStoreError("");
    let done = 0;
    for (const entry of updates) {
      try {
        await api.install(entry.slug);
        done += 1;
      } catch (exc) {
        setStoreError(message(exc));
        break;
      }
    }
    await refreshAfterChange();
    await fetchCatalog();
    setBusy("");
    if (done) setNotice(t("widgets.updated_all", { count: done }));
  };

  /** The disk, the catalog and the updates, and a word on what changed. */
  const checkForNew = async () => {
    setBusy("__check");
    setNotice("");
    const before = new Set((catalog ?? []).map((s) => s.slug));
    const parts: string[] = [];
    try {
      const scan = await api.rescanPlugins();
      if (scan.new.length) parts.push(t("widgets.check_new", { names: scan.new.join(", ") }));
      await refreshAfterChange();
    } catch (exc) {
      setStoreError(message(exc));
    }
    const after = await fetchCatalog();
    const fresh = after.filter((s) => !before.has(s.slug));
    if (catalog !== null && fresh.length) {
      parts.push(t("widgets.check_store", { names: fresh.map((s) => s.name).join(", ") }));
    }
    const open = after.filter((s) => s.update).length;
    if (open) parts.push(t("widgets.check_updates", { count: open }));
    setNotice(parts.length ? parts.join(" · ") : t("widgets.check_nothing"));
    setBusy("");
  };

  if (!settings) return null;

  if (detail) {
    const fromStore = (catalog ?? []).find((s) => s.slug === detail.id) ?? null;
    if (detail.kind === "store") {
      return (
        <div className="view wide">
          <StoreDetail
            slug={detail.id}
            known={fromStore}
            busy={busy === detail.id}
            user={user}
            onInstall={(entry) => {
              // Back to the list afterwards: the plugin is on the machine now,
              // and the page would otherwise go on offering to install it.
              void install(entry).then(() => setDetail(null));
            }}
            onBack={() => setDetail(null)}
          />
        </div>
      );
    }
    const meta = detail.kind === "theme" ? themeMeta[detail.id] : widgetMeta[detail.id];
    if (meta) {
      return (
        <div className="view wide">
          <InstalledDetail
            id={detail.id}
            kind={detail.kind}
            meta={meta}
            storeEntry={fromStore}
            user={user}
            onBack={() => setDetail(null)}
          />
        </div>
      );
    }
  }

  return (
    <div className="view wide">
      <div className="page-head">
        <h2>{t("widgets.title")}</h2>
        <div className="inline">
          <StoreAccount user={user} onUser={setUser} />
          <button type="button" className="btn" onClick={() => setSubmitOpen(true)}>
            {t("widgets.submit")}
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy === "__check"}
            onClick={() => void checkForNew()}
          >
            {busy === "__check" ? t("widgets.checking") : t("widgets.check")}
          </button>
          <button type="button" className="btn primary" onClick={() => setInstallOpen(true)}>
            {t("widgets.install_local")}
          </button>
        </div>
      </div>

      {/* At the top, not in a corner: a reviewer who misses it only learns
          of a waiting submission when looking on their own. */}
      {pending && pending.submissions + pending.reports > 0 && (
        <div className="update-bar">
          <span>
            {pending.submissions > 0 &&
              (pending.submissions === 1
                ? t("widgets.pending_submission")
                : t("widgets.pending_submissions", { count: pending.submissions }))}
            {pending.submissions > 0 && pending.reports > 0 && " · "}
            {pending.reports > 0 &&
              (pending.reports === 1
                ? t("widgets.pending_report")
                : t("widgets.pending_reports", { count: pending.reports }))}
          </span>
          {pending.url && (
            <button type="button" className="btn small" onClick={() => void openExternal(pending.url)}>
              {t("widgets.open_review")}
            </button>
          )}
        </div>
      )}

      {updates.length > 0 && (
        <div className="update-bar">
          <span>
            {t("widgets.updates_available", { count: updates.length })}
            {": "}
            {updates
              .map((u) => `${pick(u.i18n?.name, u.name)} ${u.installed_version} → ${u.latest.version}`)
              .join(", ")}
          </span>
          <button
            type="button"
            className="btn primary small"
            disabled={busy !== ""}
            onClick={() => void updateAll()}
          >
            {busy === "__all" ? t("widgets.installing") : t("widgets.update_all")}
          </button>
        </div>
      )}

      {storeError && <p className="error-note">{storeError}</p>}
      {notice && <p className="hint">{notice}</p>}

      <div className="plugin-tabs" role="tablist">
        {TYPES.map((of) => (
          <button
            key={of}
            type="button"
            role="tab"
            aria-selected={type === of}
            className={type === of ? "plugin-tab active" : "plugin-tab"}
            onClick={() => {
              setType(of);
              // The chosen topic may not exist for the other type, and an
              // empty list without an obvious reason confuses.
              setFilter("all");
            }}
          >
            {t(`widgets.type.${of}`)}
            <span className="plugin-tab-count">{entriesOf(of).length}</span>
          </button>
        ))}
      </div>

      <div className="plugin-layout">
        <nav className="plugin-categories" aria-label={t("widgets.title")}>
          <CategoryButton
            label={t("widgets.category.all")}
            count={entries.length}
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
          <CategoryButton
            label={t("widgets.category.installed")}
            count={installedCount}
            active={filter === "installed"}
            onClick={() => setFilter("installed")}
          />
          {/* Themes have no topics; their list is short enough as it is. */}
          {type === "widget" && CATEGORIES.map((c) => (
            <CategoryButton
              key={c}
              label={t(`widgets.category.${c}`)}
              count={counts.get(c) ?? 0}
              active={filter === c}
              onClick={() => setFilter(c)}
            />
          ))}
        </nav>

        <div className="plugin-content">
          {type === "theme" && <p className="hint">{t("widgets.themes_hint")}</p>}
          {visible.length === 0 ? (
            <p className="empty-note">{t("widgets.empty_category")}</p>
          ) : (
            <div className="plugin-list">
              {visible.map((e) =>
                e.kind === "theme" ? (
                  <ThemeCard
                    key={e.id}
                    onOpen={() => setDetail({ kind: "theme", id: e.id })}
                    id={e.id}
                    meta={e.meta}
                    active={settings.default_theme === e.id}
                    update={(catalog ?? []).find((s) => s.slug === e.id && s.update) ?? null}
                    busy={busy === e.id}
                    onUpdate={(s) => void install(s)}
                  />
                ) : e.kind === "widget" ? (
                  <WidgetCard
                    key={e.id}
                    onOpen={() => setDetail({ kind: "widget", id: e.id })}
                    id={e.id}
                    meta={e.meta}
                    update={(catalog ?? []).find((s) => s.slug === e.id && s.update) ?? null}
                    busy={busy === e.id}
                    onUpdate={(s) => void install(s)}
                  />
                ) : (
                  <StoreCard
                    key={e.id}
                    onOpen={() => setDetail({ kind: "store", id: e.id })}
                    entry={e.entry}
                    isTheme={type === "theme"}
                    busy={busy === e.id}
                    onInstall={() => void install(e.entry)}
                  />
                ),
              )}
            </div>
          )}
        </div>
      </div>

      {installOpen && <LocalInstall onClose={() => setInstallOpen(false)} />}
      {submitOpen && <StoreSubmit user={user} onClose={() => setSubmitOpen(false)} />}
    </div>
  );
}

function CategoryButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={count === 0}
      className={active ? "category active" : count === 0 ? "category empty" : "category"}
      onClick={onClick}
    >
      {label}
      <span className="category-count">{count}</span>
    </button>
  );
}

function CardIcon({
  name,
  accent,
  symbol,
  iconUrl,
}: {
  name: string;
  accent: string;
  symbol: string;
  iconUrl: string;
}) {
  const [failed, setFailed] = useState(false);
  if (iconUrl && !failed) {
    const src = iconUrl.startsWith("/") ? `${API_BASE}${iconUrl}` : iconUrl;
    return <img className="plugin-icon" src={src} alt="" onError={() => setFailed(true)} />;
  }
  return (
    <span
      className="plugin-icon placeholder"
      style={{ background: accent || "var(--accent)" }}
      aria-hidden="true"
    >
      {symbol ? <Icon icon={symbol} /> : name.slice(0, 1).toUpperCase()}
    </span>
  );
}


function WidgetCard({
  id,
  meta,
  update,
  busy,
  onUpdate,
  onOpen,
}: {
  onOpen: () => void;
  id: string;
  meta: WidgetMeta;
  update: StoreEntry | null;
  busy: boolean;
  onUpdate: (entry: StoreEntry) => void;
}) {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const saveSettings = useStore((s) => s.saveSettings);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const name = pick(meta.name, id);
  const configured = settings?.modules ?? {};
  const hasModules = meta.modules.length > 0;
  const enabled = hasModules && meta.modules.every((m) => configured[m]?.enabled);

  const toggle = async (on: boolean) => {
    setError("");
    try {
      await saveSettings({
        modules: Object.fromEntries(meta.modules.map((m) => [m, { enabled: on }])),
      });
    } catch (exc) {
      setError(message(exc));
    }
  };

  const remove = async () => {
    if (!window.confirm(t("widgets.remove_confirm", { name }))) return;
    setError("");
    try {
      await api.uninstall(id);
      await refreshAfterChange();
    } catch (exc) {
      setError(message(exc));
    }
  };

  const details = [
    `v${meta.version}`,
    meta.author && !meta.builtin ? t("widgets.by_author", { author: meta.author }) : "",
    meta.source === "local" ? t("widgets.local") : "",
  ].filter(Boolean);

  return (
    <div
      className={!hasModules || enabled ? "plugin-card" : "plugin-card disabled"}
      style={{ borderLeftColor: meta.accent || undefined }}
    >
      <div className="plugin-head">
        <CardIcon name={name} accent={meta.accent} symbol={meta.symbol} iconUrl={meta.icon_url} />
        {hasModules ? (
          <span
            className={enabled ? "status-dot online" : "status-dot offline"}
            title={enabled ? t("widgets.running") : t("widgets.off")}
          />
        ) : (
          <span className="dot-placeholder" />
        )}
        <div className="plugin-title">
          <button type="button" className="plugin-name" onClick={onOpen}>
            {name}
          </button>
          <small>{details.join(" · ")}</small>
        </div>

        {update && <span className="line-break" aria-hidden="true" />}
        {update && (
          <button
            type="button"
            className="btn small update"
            disabled={busy}
            onClick={() => onUpdate(update)}
          >
            {busy ? t("widgets.installing") : t("widgets.update", { version: update.latest.version })}
          </button>
        )}

        {meta.builtin ? (
          <span className="badge">{t("widgets.builtin")}</span>
        ) : (
          <button type="button" className="btn small danger" onClick={() => void remove()}>
            {t("widgets.remove")}
          </button>
        )}

        {hasModules && (
          <label className="switch" title={t("widgets.enabled")}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => void toggle(event.target.checked)}
            />
            <span />
          </label>
        )}
      </div>

      <p className="plugin-description">{pick(meta.summary)}</p>
      {meta.warnings && <Warnings warnings={meta.warnings} />}
      {error && <p className="error-text">{error}</p>}

      {enabled && (
        <button type="button" className="btn small" onClick={() => setOpen(true)}>
          {t("widgets.settings")}
        </button>
      )}

      {open && <ModuleSettingsDialog title={name} modules={meta.modules} onClose={() => setOpen(false)} />}
    </div>
  );
}

/**
 * The settings of a widget's modules: interval and whatever each module
 * declares in its `settings_schema`. This is what the Modules tab used to
 * show, now reached from the widget that needs it.
 */
function ModuleSettingsDialog({
  title,
  modules,
  onClose,
}: {
  title: string;
  modules: string[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const schemas = useStore((s) => s.schemas);
  const saveSettings = useStore((s) => s.saveSettings);
  const [draft, setDraft] = useState<Record<string, ModuleSettings>>(() =>
    Object.fromEntries(
      modules.map((m) => [m, settings?.modules[m] ?? { enabled: true, interval: null }]),
    ),
  );
  const [dirty, setDirty] = useState(false);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState("");

  const edit = (name: string, next: ModuleSettings) => {
    setDraft((current) => ({ ...current, [name]: next }));
    setDirty(true);
    setState("idle");
  };

  const save = async (): Promise<boolean> => {
    setState("saving");
    setError("");
    try {
      await saveSettings({ modules: draft });
      setDirty(false);
      setState("saved");
      return true;
    } catch (exc) {
      setError(message(exc));
      setState("idle");
      return false;
    }
  };

  const close = async () => {
    if (dirty && window.confirm(t("widgets.save_on_close"))) {
      if (!(await save())) return;
    }
    onClose();
  };

  return (
    <Modal
      title={`${title} · ${t("widgets.settings")}`}
      width={620}
      onClose={() => void close()}
      footer={
        <>
          {state === "saved" && !dirty && <span className="hint">{t("common.saved")}</span>}
          {error && <span className="error-text">{error}</span>}
          <button
            type="button"
            className="btn primary"
            disabled={state === "saving"}
            onClick={() => void save()}
          >
            {state === "saving" ? t("common.saving") : t("common.save")}
          </button>
        </>
      }
    >
      {modules.length > 1 && <p className="hint">{t("widgets.shared_module_hint")}</p>}
      {modules.map((name) => {
        const current = draft[name]!;
        const schema = schemas[name] ?? [];
        return (
          <section key={name} className="module-block">
            {modules.length > 1 && (
              <header className="module-block-head">
                <h3>
                  {t("widgets.module_named", { name })}
                </h3>
                <label className="switch" title={t("widgets.enabled")}>
                  <input
                    type="checkbox"
                    checked={current.enabled}
                    onChange={(e) => edit(name, { ...current, enabled: e.target.checked })}
                  />
                  <span />
                </label>
              </header>
            )}
            <div className="row">
              <label htmlFor={`${name}-interval`}>{t("modules.interval")}</label>
              <div className="control">
                <div className="inline">
                  <input
                    id={`${name}-interval`}
                    type="number"
                    min={0.05}
                    step={0.05}
                    value={current.interval ?? ""}
                    placeholder={t("modules.interval_default")}
                    onChange={(e) =>
                      edit(name, {
                        ...current,
                        interval: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  />
                  <span className="muted">{t("modules.interval_seconds")}</span>
                </div>
                <div className="hint">{t("modules.interval_help")}</div>
              </div>
            </div>
            {schema
              .filter((field) => applies(field, schema, (key) => readPath(current, key)))
              .map((field) => (
                <Field
                  key={field.key}
                  field={field}
                  value={readPath(current, field.key)}
                  onChange={(value) => edit(name, writePath(current, field.key, value) as ModuleSettings)}
                />
              ))}
          </section>
        );
      })}
    </Modal>
  );
}

/**
 * A theme as a card. Its picture is a strip in its own colours, the same
 * preview the design page shows. Choosing a theme stays on the design page;
 * here it is installed, updated or removed.
 */
function ThemeCard({
  id,
  meta,
  active,
  update,
  busy,
  onUpdate,
  onOpen,
}: {
  onOpen: () => void;
  id: string;
  meta: ThemeMeta;
  active: boolean;
  update: StoreEntry | null;
  busy: boolean;
  onUpdate: (entry: StoreEntry) => void;
}) {
  const { t } = useTranslation();
  const setView = useStore((s) => s.setView);
  const [error, setError] = useState("");
  const name = themeLabel(id, meta.name);

  const remove = async () => {
    if (!window.confirm(t("widgets.remove_theme_confirm", { name }))) return;
    setError("");
    try {
      await api.uninstall(id);
      await refreshAfterChange();
    } catch (exc) {
      setError(message(exc));
    }
  };

  const details = [
    `v${meta.version}`,
    meta.author ? t("widgets.by_author", { author: meta.author }) : "",
    meta.source === "local" ? t("widgets.local") : "",
  ].filter(Boolean);

  return (
    <div className="plugin-card">
      <ThemeSwatch name={id} className="theme-swatch card-swatch" />
      <div className="plugin-head">
        <div className="plugin-title">
          <button
            type="button"
            className={meta.builtin ? "plugin-name capitalize" : "plugin-name"}
            onClick={onOpen}
          >
            {name}
          </button>
          <small>{details.join(" · ")}</small>
        </div>
        {update && (
          <button
            type="button"
            className="btn small update"
            disabled={busy}
            onClick={() => onUpdate(update)}
          >
            {busy ? t("widgets.installing") : t("widgets.update", { version: update.latest.version })}
          </button>
        )}
        {active && <span className="tag-store">{t("widgets.theme_active")}</span>}
        {meta.builtin ? (
          <span className="badge">{t("widgets.builtin")}</span>
        ) : (
          <button type="button" className="btn small danger" onClick={() => void remove()}>
            {t("widgets.remove")}
          </button>
        )}
      </div>
      {pick(meta.summary) && <p className="plugin-description">{pick(meta.summary)}</p>}
      {error && <p className="error-text">{error}</p>}
      {!active && (
        <button type="button" className="btn small" onClick={() => setView("theme")}>
          {t("widgets.choose_in_design")}
        </button>
      )}
    </div>
  );
}

function StoreCard({
  entry,
  isTheme,
  busy,
  onInstall,
  onOpen,
}: {
  onOpen: () => void;
  entry: StoreEntry;
  isTheme: boolean;
  busy: boolean;
  onInstall: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const name = pick(entry.i18n?.name, entry.name);
  const hasWarnings = entry.latest.warnings.length > 0;

  return (
    <div className="plugin-card store">
      <div className="plugin-head">
        {!isTheme && (
          <CardIcon
            name={name}
            accent=""
            symbol=""
            iconUrl={entry.latest.icon_url ? images.storeIcon(entry.slug, entry.latest.version) : ""}
          />
        )}
        <div className="plugin-title">
          <button type="button" className="plugin-name" onClick={onOpen}>
            {name}
          </button>
          <small>
            v{entry.latest.version} · {t("widgets.by_author", { author: entry.author })}
            {" · ♥ "}{entry.rating.up}
          </small>
        </div>
        <span className="tag-store">{t("widgets.tag_store")}</span>
      </div>

      <p className="plugin-description">{pick(entry.i18n?.summary, entry.summary)}</p>
      <Warnings warnings={entry.latest.warnings} />
      {!entry.compatible && (
        <p className="error-text">
          {t("widgets.needs_version", { version: entry.latest.min_app_version })}
        </p>
      )}

      <div className="inline">
        <button
          type="button"
          className={confirming ? "btn danger" : "btn primary"}
          disabled={busy || !entry.compatible}
          onClick={() => {
            // Code from someone else runs in the backend. With findings, the
            // first click only shows them; the second installs.
            if (hasWarnings && !confirming) {
              setConfirming(true);
              return;
            }
            setConfirming(false);
            onInstall();
          }}
        >
          {busy
            ? t("widgets.installing")
            : confirming
              ? t("widgets.install_anyway")
              : t("widgets.install")}
        </button>
      </div>
    </div>
  );
}

/** Installing from this machine: a zip, or a folder holding manifest.json. */
function LocalInstall({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const run = async (task: () => ReturnType<typeof api.installFolder>) => {
    setBusy(true);
    setResult(null);
    try {
      const answer = await task();
      await refreshAfterChange();
      setResult({
        ok: true,
        text: t("widgets.installed", {
          name: pick(answer.plugin.name, answer.plugin.id),
          version: answer.plugin.version,
        }),
      });
      setPath("");
    } catch (exc) {
      setResult({ ok: false, text: message(exc) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t("widgets.install_local")} width={560} onClose={onClose}>
      <p className="hint">{t("widgets.install_local_hint")}</p>
      <div className="row">
        <label>{t("widgets.archive")}</label>
        <div className="control">
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void run(() => api.installUpload(file));
            }}
          />
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            {t("widgets.choose_zip")}
          </button>
        </div>
      </div>
      <div className="row">
        <label htmlFor="install-folder">{t("widgets.folder")}</label>
        <div className="control">
          <div className="inline">
            <input
              id="install-folder"
              value={path}
              className="grow"
              placeholder="~/Projekte/mein-widget"
              onChange={(e) => setPath(e.target.value)}
            />
            <button
              type="button"
              className="btn primary"
              disabled={busy || !path.trim()}
              onClick={() => void run(() => api.installFolder(path.trim()))}
            >
              {busy ? t("widgets.installing") : t("widgets.install")}
            </button>
          </div>
          <div className="hint">{t("widgets.folder_hint")}</div>
        </div>
      </div>
      {result && <p className={result.ok ? "hint" : "error-text"}>{result.text}</p>}
    </Modal>
  );
}

/**
 * Signing in to the store, in the head of the page.
 *
 * Signed in: the handle and a way out. Signed out: the device flow. The
 * store hands out a code, the user types it on github.com, and this window
 * asks again and again whether that happened. Not on a fixed interval but
 * as a loop that sets itself again, because of `slow_down`: GitHub then
 * wants five seconds more between two questions and otherwise answers the
 * same until the code expires.
 */
function StoreAccount({
  user,
  onUser,
}: {
  user: StoreUser | null;
  onUser: (user: StoreUser | null) => void;
}) {
  const { t } = useTranslation();
  const [device, setDevice] = useState<DeviceStart | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);
  // Each sign-in gets a number. A question still on its way when the user
  // cancels does not set itself up again afterwards.
  const round = useRef(0);

  const stop = useCallback(() => {
    round.current += 1;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  const signIn = async () => {
    setError("");
    stop();
    const mine = round.current;
    try {
      const start = await api.storeDeviceStart();
      if (mine !== round.current) return;
      setDevice(start);
      let interval = Math.max(start.interval, 5) * 1000;

      const poll = async () => {
        try {
          const answer = await api.storeDevicePoll(start.device_code);
          if (mine !== round.current) return;
          if (answer.status === "ok" && answer.user) {
            stop();
            setDevice(null);
            onUser(answer.user);
            return;
          }
          if (answer.status === "slow_down") interval += (answer.backoff ?? 5) * 1000;
          timer.current = window.setTimeout(() => void poll(), interval);
        } catch (exc) {
          if (mine !== round.current) return;
          stop();
          setDevice(null);
          setError(message(exc));
        }
      };
      timer.current = window.setTimeout(() => void poll(), interval);
    } catch (exc) {
      if (mine !== round.current) return;
      setError(message(exc));
    }
  };

  if (device) {
    return (
      <div className="store-account">
        <span className="hint">{t("widgets.enter_code")}</span>
        <code className="store-code">{device.user_code}</code>
        <button
          type="button"
          className="btn"
          onClick={() => void openExternal(device.verification_uri)}
        >
          {t("widgets.open_github")}
        </button>
        <button
          type="button"
          className="btn small"
          onClick={() => {
            stop();
            setDevice(null);
          }}
        >
          {t("common.cancel")}
        </button>
      </div>
    );
  }

  if (user) {
    return (
      <div className="store-account">
        <span className="hint">{user.handle}</span>
        <button
          type="button"
          className="btn"
          onClick={() =>
            void api
              .storeLogout()
              .then(() => onUser(null))
              .catch((exc: unknown) => setError(message(exc)))
          }
        >
          {t("widgets.sign_out")}
        </button>
      </div>
    );
  }

  return (
    <div className="store-account">
      {error && <span className="error-note">{error}</span>}
      <button type="button" className="btn" onClick={() => void signIn()}>
        {t("widgets.sign_in")}
      </button>
    </div>
  );
}
