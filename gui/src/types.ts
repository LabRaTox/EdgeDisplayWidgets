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
}

export interface Health {
  ok: boolean;
  version: string;
  clients: number;
}

/** `/api/widgets` — the available widgets and the variants they declare. */
export interface WidgetsResponse {
  widgets: string[];
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

export type View =
  | "theme"
  | "modules"
  | "weather"
  | "youtube"
  | "actions"
  | "layout"
  | "system"
  | "about";
