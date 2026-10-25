/**
 * Shapes the backend hands out. These mirror `_settings_view` in
 * backend/main.py and the module schema from `/api/modules/schema`.
 */

/** One editable field a module declares (backend/modules/base.py SettingField). */
export interface SettingField {
  key: string;
  type: "bool" | "int" | "float" | "text" | "select" | "list" | "color";
  label_key: string;
  default: unknown;
  secret: boolean;
  min: number | null;
  max: number | null;
  step: number | null;
  options: string[] | null;
  placeholder_key: string | null;
  help_key: string | null;
  group_key: string | null;
  /** Display text per option, when the value itself is not readable. */
  option_labels: string[] | null;
  /** The same, but as i18n keys, for a list that is fixed in the schema. */
  option_label_keys: string[] | null;
  options_source: string | null;
  /** Shown only while these other fields have these values (one or a list). */
  depends_on: Record<string, unknown> | null;
}

/** Everything under `modules.<name>` — the common keys plus whatever the module adds. */
export interface ModuleSettings {
  enabled: boolean;
  interval: number | null;
  [key: string]: unknown;
}

export interface WidgetPlacement {
  id: string;
  col: number;
  row: number;
  colspan: number;
  rowspan: number;
  variant?: string | null;
  options?: Record<string, unknown>;
  /** Legacy placement by named grid area; the backend resolves it to col/row. */
  area?: string | null;
}

export interface GridDef {
  columns: string;
  rows: string;
  areas: string[];
}

export interface Page {
  id: string;
  title: string;
  grid: GridDef;
  widgets: WidgetPlacement[];
}

export interface Settings {
  default_theme: string;
  /** "auto" | "en" | "de" — see AppConfig.default_language. */
  default_language: string;
  modules: Record<string, ModuleSettings>;
  pages: Page[];
}

/**
 * A quick-action tile as `/api/quick_actions/config` returns it — the
 * unscrubbed shape, commands and headers included. `/api/settings` deliberately
 * strips those, which is why the editor uses the dedicated endpoint.
 *
 * The deck is a Stream-Deck-style grid: `x`/`y` place a tile on `page`, `w`/`h`
 * are its span in cells, and a tile with x/y unset flows into the next free
 * cell. A folder carries nested `tiles` and the position of its back button.
 */
export interface QuickAction {
  id: string;
  label?: string;
  kind: "shell" | "http" | "folder";
  icon?: string;
  color?: string | null;
  text_color?: string | null;
  confirm?: boolean;
  detach?: boolean;
  w?: number;
  h?: number;
  page?: number;
  x?: number | null;
  y?: number | null;
  /** This tile's label and icon size on the display, in pixels; empty is the default. */
  label_size?: number | null;
  icon_size?: number | null;
  back_x?: number;
  back_y?: number;
  command?: string[] | null;
  url?: string | null;
  method?: string;
  headers?: Record<string, string>;
  params?: Record<string, unknown>;
  /** YAML key `json`; the backend keeps the alias on the wire. */
  json?: unknown;
  tiles?: QuickAction[];
  status?: QuickActionStatus | null;
}

export interface QuickActionStatus {
  kind: "shell" | "http";
  command?: string[];
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  params?: Record<string, string>;
  match?: string;
}

export interface QuickActionsConfig {
  actions: QuickAction[];
  columns: number;
  rows: number;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface ThemesResponse {
  themes: string[];
  default: string;
  /** Per theme: its name and where it comes from. */
  meta?: Record<string, ThemeMeta>;
}

export interface ThemeMeta {
  name: Localized;
  summary: Localized;
  builtin: boolean;
  version: string;
  author: string;
  license: string;
  source?: "store" | "local";
  description: Localized;
  changelog: Localized;
  support: string;
  screenshots: number;
  icon_url: string;
}

export interface Health {
  ok: boolean;
  version: string;
  clients: number;
}

/** `/api/widgets` — the available widgets and the variants they declare. */
export interface WidgetsResponse {
  widgets: string[];
  /** The ones among `widgets` that were installed from the store. */
  installed?: string[];
  /** What the widget page shows on each card. */
  meta?: Record<string, WidgetMeta>;
  /** Only widgets that declare variants appear here. */
  variants: Record<string, string[]>;
  /** Only widgets that declare options appear here. */
  options: Record<string, SettingField[]>;
}

/** `/api/autostart` — whether the dashboard starts itself at login. */
export interface AutostartStatus {
  /** False when there is no systemd user session to switch anything in. */
  supported: boolean;
  enabled: boolean;
  /** Which units are installed in ~/.config/systemd/user. */
  units: string[];
  /** Why it cannot be switched, when `supported` is false. */
  reason: string | null;
}

/** A manifest text: one string, or one per language code. */
export type Localized = string | Record<string, string>;

/** One widget as a card on the widget page, built-in or installed. */
export interface WidgetMeta {
  name: Localized;
  summary: Localized;
  category: string;
  accent: string;
  /** A Tabler name (`ti:cpu`); built-in widgets have one. */
  symbol: string;
  /** An image in an installed widget's folder, relative to the backend. */
  icon_url: string;
  modules: string[];
  builtin: boolean;
  version: string;
  license: string;
  author?: string;
  source?: "store" | "local";
  warnings?: StoreWarning[];
  description: Localized;
  changelog: Localized;
  support: string;
  /** How many screenshots the manifest lists; fetched by position. */
  screenshots: number;
}

/** A finding of the store's review that the user should see before installing. */
export interface StoreWarning {
  kind: string;
  value: string;
  file: string;
  line: number | null;
}

export interface StoreVersion {
  version: string;
  sha256: string;
  size: number;
  min_app_version: string | null;
  downloads: number;
  released_at: string;
  icon_url: string | null;
  screenshot_urls: string[];
  changelog: string | null;
  changelog_i18n: Localized | null;
  warnings: StoreWarning[];
  /** Only in the detail answer: where this version stands. */
  state?: string;
  note?: string | null;
}

export interface StoreEntry {
  slug: string;
  /** `widget` or `theme`. */
  kind: string;
  name: string;
  summary: string;
  category: string;
  author: string;
  license: string | null;
  source_url: string | null;
  rating: { up: number; down: number };
  latest: StoreVersion;
  i18n?: { name: Localized | null; summary: Localized | null; description?: Localized | null };
  /** Only in the detail answer. */
  description?: string | null;
  versions?: StoreVersion[];
  /** Added by the backend: what is installed here, if anything. */
  installed_version: string | null;
  update: boolean;
  compatible: boolean;
}

export interface StoreCatalog {
  count: number;
  plugins: StoreEntry[];
}

export interface InstalledPlugin {
  id: string;
  version: string;
  name: Localized;
  summary: Localized;
  modules: string[];
  author: string;
  warnings: StoreWarning[];
  installed_at: number | null;
}

/** One comment under a rating. */
export interface StoreComment {
  value: number;
  comment: string;
  author: string;
  at: string;
}

/** How a plugin is rated, and how you rated it. */
export interface StoreRating {
  up: number;
  down: number;
  mine: number | null;
  comment: string | null;
  comments: StoreComment[];
  /** True when the author asks: one cannot rate one's own plugin. */
  own?: boolean;
}

export interface StoreUser {
  id: number;
  handle: string;
  permissions: string[];
  banned: boolean;
}

/** What waits for review; only sent to accounts allowed to review. */
export interface StorePending {
  submissions: number;
  reports: number;
  url: string;
}

export interface DeviceStart {
  device_code: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

/** What the store says about an archive it just took. */
export interface StoreUploadResult {
  slug: string;
  version: string;
  sha256: string;
  status: string;
  findings: number;
  warnings: number;
  message: string;
}

export interface StoreMine {
  count: number;
  plugins: {
    slug: string;
    name: string;
    visibility: string;
    removedAt: string | null;
    removedReason: string | null;
    versions: {
      version: string;
      status: string;
      stateNote: string | null;
      reviewNote: string | null;
      submittedAt: string;
      reviewedAt: string | null;
      downloadCount: number;
    }[];
  }[];
}

export type View =
  | "theme"
  | "widgets"
  | "weather"
  | "youtube"
  | "actions"
  | "layout"
  | "system"
  | "about";
