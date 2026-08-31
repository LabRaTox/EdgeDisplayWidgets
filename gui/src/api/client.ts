/**
 * Talking to the dashboard backend.
 *
 * Absolute base URL rather than a Vite proxy, so the same code works in three
 * places: the dev server on 5173, the Tauri window, and a plain browser tab
 * pointed at the backend itself.
 *
 * **The Tauri case is why this needs care.** Inside the window the page lives
 * at `http://tauri.localhost/` — protocol `http:`, but no port and a host
 * name with no server behind it, just Tauri's own file server. Treating that
 * origin as the backend sends every request into the void and leaves the
 * window blank with nothing in the console. Hence: only trust our own origin
 * when it can actually be a backend.
 */

import type {
  AutostartStatus,
  Health,
  QuickActionsConfig,
  Settings,
  ThemesResponse,
  WidgetsResponse,
} from "../types";

const DEFAULT_BASE = "http://127.0.0.1:8765";

/** Ports where the Vite dev server lives, not the backend. */
const DEV_SERVER_PORTS = new Set(["5173", "5174", "4173"]);
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function resolveBase(): string {
  const configured = import.meta.env.VITE_BACKEND_URL as string | undefined;
  if (configured) return configured;

  if (typeof window !== "undefined") {
    const { protocol, hostname, port, origin } = window.location;
    const servedByBackend =
      protocol.startsWith("http") &&
      LOCAL_HOSTS.has(hostname) &&
      port !== "" &&
      !DEV_SERVER_PORTS.has(port);
    if (servedByBackend) return origin;
  }
  return DEFAULT_BASE;
}

export const API_BASE: string = resolveBase();

/** An error the backend explained; `status` is the HTTP code. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    // FastAPI puts the reason in `detail`; fall back to the raw body.
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string; error?: string };
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* not JSON — keep the status line */
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  settings: () => request<Settings>("/api/settings"),
  moduleSchemas: () =>
    request<{ modules: Record<string, import("../types").SettingField[]> }>(
      "/api/modules/schema",
    ),
  themes: () => request<ThemesResponse>("/api/themes"),
  widgets: () => request<WidgetsResponse>("/api/widgets"),

  /**
   * Write a *partial* settings object. Unspecified keys keep their value, so
   * every view can send just the block it owns.
   */
  saveSettings: (patch: Record<string, unknown>) =>
    request<{ ok: boolean; settings: Settings }>("/api/settings", {
      method: "POST",
      body: JSON.stringify(patch),
    }),

  quickActions: () => request<QuickActionsConfig>("/api/quick_actions/config"),
  saveQuickActions: (config: QuickActionsConfig) =>
    request<{ ok: boolean; count: number }>("/api/quick_actions/config", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  runQuickAction: (id: string) =>
    request<{ ok: boolean; error?: string; state?: string }>(
      `/api/quick_actions/${encodeURIComponent(id)}/run`,
      { method: "POST" },
    ),

  autostart: () => request<AutostartStatus>("/api/autostart"),
  /**
   * Switches both user units at once. Takes effect at the next login: the
   * backend is answering this very request and will not restart itself over
   * a checkbox.
   */
  setAutostart: (enabled: boolean) =>
    request<AutostartStatus>("/api/autostart", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  /** The kiosk's translation files — reused so labels stay in one place. */
  locale: (code: string) =>
    request<Record<string, string>>(`/locales/${encodeURIComponent(code)}.json`),
};

/** True when this UI runs inside the app rather than in a browser tab. */
export function inApp(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Ask the window to start the dashboard's services.
 *
 * Only possible inside the app: a browser tab cannot run systemctl, which is
 * why the offline banner falls back to naming the command there.
 */
export async function startDashboard(): Promise<void> {
  if (!inApp()) throw new Error("not running in the settings window");
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("start_dashboard");
}

/**
 * Open a link outside this window.
 *
 * In the app it goes through Tauri, which hands it to the browser; a normal
 * link would navigate the settings UI away instead. In a browser tab a new
 * tab is exactly right.
 */
export async function openExternal(url: string): Promise<void> {
  if (!inApp()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_url", { url });
}

/** Poll `/api/health` until the backend answers, or give up. */
export async function waitForBackend(timeoutMs = 15000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await api.health();
      return true;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
  return false;
}

/**
 * Watch the backend's WebSocket to know whether it is alive, and to notice
 * settings written elsewhere (the kiosk, a second window, a hand-edited YAML
 * that was reloaded).
 *
 * We do not consume the module data stream — this window shows configuration,
 * not measurements — but the socket is the cheapest liveness signal there is,
 * and it costs the backend nothing to have one more client.
 */
export function connectEvents(handlers: {
  onSettings?: (settings: Settings) => void;
  onStatus?: (online: boolean) => void;
}): () => void {
  const url = `${API_BASE.replace(/^http/, "ws")}/ws`;
  let socket: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let retryTimer: number | undefined;

  const connect = () => {
    if (closed) return;
    try {
      socket = new WebSocket(url);
    } catch {
      scheduleRetry();
      return;
    }
    socket.addEventListener("open", () => {
      attempt = 0;
      handlers.onStatus?.(true);
    });
    socket.addEventListener("message", (event) => {
      let frame: { event?: string; settings?: Settings };
      try {
        frame = JSON.parse(event.data as string);
      } catch {
        return;
      }
      // Module data frames carry `module`; only control frames interest us.
      if (frame.event === "settings" && frame.settings) {
        handlers.onSettings?.(frame.settings);
      }
    });
    socket.addEventListener("close", () => {
      // A socket we closed ourselves says nothing about the backend. Without
      // this check, tearing down (React re-running the effect, or the window
      // going away) reports an outage that is not happening.
      if (closed) return;
      handlers.onStatus?.(false);
      scheduleRetry();
    });
    socket.addEventListener("error", () => {
      /* 'close' follows; retry is handled there */
    });
  };

  const scheduleRetry = () => {
    if (closed) return;
    attempt += 1;
    const delay = Math.min(250 * 2 ** (attempt - 1), 5000);
    retryTimer = window.setTimeout(connect, delay);
  };

  connect();
  return () => {
    closed = true;
    window.clearTimeout(retryTimer);
    socket?.close();
  };
}
