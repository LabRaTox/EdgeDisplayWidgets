/**
 * Central state of the settings window.
 *
 * The canonical copy of the configuration lives in the backend, so this store
 * mirrors rather than owns it: every view edits a local draft and posts it,
 * and whatever comes back — from the response or from the `settings` frame on
 * the socket — replaces the mirror. That matters because this window is not
 * the only writer: the backend also rewrites the config when someone edits
 * the YAML and reloads, and a second window would write it too.
 */

import { create } from "zustand";

import { api, inApp, startDashboard, waitForBackend } from "./api/client";
import type {
  QuickActionsConfig,
  SettingField,
  Settings,
  View,
} from "./types";

interface StoreState {
  /** False until the first successful load — views show nothing before that. */
  ready: boolean;
  /** True while the services are being started on our behalf. */
  starting: boolean;
  online: boolean;
  version: string;
  view: View;

  settings: Settings | null;
  schemas: Record<string, SettingField[]>;
  themes: string[];
  widgets: string[];
  /** Per widget: the display variants it offers, if any. */
  widgetVariants: Record<string, string[]>;
  quickActions: QuickActionsConfig | null;

  /** Last load error, so the banner can say what actually went wrong. */
  error: string | null;

  /** `afterStart` guards the one retry that follows starting the services. */
  load: (afterStart?: boolean) => Promise<void>;
  setView: (view: View) => void;
  setOnline: (online: boolean) => void;
  /** Adopt settings the backend announced (saved elsewhere). */
  adoptSettings: (settings: Settings) => void;
  /** Post a partial settings object and adopt the result. */
  saveSettings: (patch: Record<string, unknown>) => Promise<void>;
  saveQuickActions: (config: QuickActionsConfig) => Promise<void>;
}

export const useStore = create<StoreState>((set, get) => ({
  ready: false,
  starting: false,
  online: false,
  version: "",
  view: "theme",

  settings: null,
  schemas: {},
  themes: [],
  widgets: [],
  widgetVariants: {},
  quickActions: null,
  error: null,

  async load(afterStart = false) {
    try {
      // Quick actions are fetched separately because their endpoint returns
      // the unmasked tile list this window is allowed to edit, while
      // /api/settings deliberately scrubs commands and headers.
      const [health, settings, schemas, themes, widgets, quickActions] =
        await Promise.all([
          api.health(),
          api.settings(),
          api.moduleSchemas(),
          api.themes(),
          api.widgets(),
          api.quickActions().catch(() => null),
        ]);
      set({
        ready: true,
        online: true,
        error: null,
        version: health.version,
        settings,
        schemas: schemas.modules,
        themes: themes.themes,
        widgets: widgets.widgets,
        widgetVariants: widgets.variants ?? {},
        quickActions,
      });
    } catch (err) {
      // Nothing answered. Inside the app that most likely means the services
      // are not running at all, which this window can fix rather than report:
      // it is usually opened from the tray, and the tray's Quit stops them.
      // Once only, so a backend that starts and then fails does not put us
      // into a loop.
      if (!afterStart && inApp()) {
        set({ starting: true, error: null });
        try {
          await startDashboard();
          if (await waitForBackend()) {
            set({ starting: false });
            await useStore.getState().load(true);
            return;
          }
        } catch (startError) {
          console.warn("could not start the dashboard:", startError);
        }
        set({ starting: false });
      }
      set({
        online: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },

  setView(view) {
    set({ view });
  },

  setOnline(online) {
    const was = get().online;
    set({ online });
    // Coming back from an outage: the configuration may have moved on while
    // we were away, so re-read rather than trust the mirror.
    if (online && !was) void get().load();
  },

  adoptSettings(settings) {
    set({ settings });
  },

  async saveSettings(patch) {
    const response = await api.saveSettings(patch);
    set({ settings: response.settings, online: true });
  },

  async saveQuickActions(config) {
    await api.saveQuickActions(config);
    // Read back: the backend fills in defaults and drops fields it does not
    // accept, and the editor should show what was actually stored.
    const stored = await api.quickActions();
    set({ quickActions: stored });
  },
}));
