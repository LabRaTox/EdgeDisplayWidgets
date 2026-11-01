import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, images, openExternal } from "../api/client";
import type { ModuleSettings } from "../types";

/** Colours a page gets, so it looks like the window around it. */
const COLORS = [
  "--bg", "--bg-raised", "--bg-sunken", "--border", "--border-strong", "--text",
  "--text-dim", "--accent", "--accent-soft", "--danger", "--ok", "--warn",
];

const MAX_HEIGHT = 6000;

/**
 * A plugin's own settings page, for what `settings_schema` cannot describe.
 *
 * The page comes from the plugin, so it runs in a sandboxed frame without an
 * origin and without network access. It talks to this window by postMessage:
 *
 *   page to window: ready, height, change, command, open
 *   window to page: init, result
 *
 * What it can reach is decided here: the settings and the commands of this
 * one module, and http(s) links for the browser. `enabled` and `interval`
 * belong to the dialog, whatever the page sends. The protocol is documented
 * in docs/widgets.md.
 */
export function PluginSettingsFrame({
  plugin,
  version,
  module,
  value,
  onChange,
}: {
  plugin: string;
  version: string;
  module: string;
  value: ModuleSettings;
  onChange: (next: ModuleSettings) => void;
}) {
  const { i18n } = useTranslation();
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(240);

  const latest = useRef({ value, onChange, language: i18n.language });
  latest.current = { value, onChange, language: i18n.language };

  // "*" because a sandboxed page has no origin to name.
  const post = useCallback((message: unknown) => {
    frame.current?.contentWindow?.postMessage(message, "*");
  }, []);

  useEffect(() => {
    const command = async (id: unknown, action: string, args: Record<string, unknown>) => {
      try {
        post({ type: "result", id, ok: true, data: await api.moduleCommand(module, action, args) });
      } catch (exc) {
        post({ type: "result", id, ok: false, error: exc instanceof ApiError ? exc.message : "" });
      }
    };

    const listener = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null) return;
      const message = data as Record<string, unknown>;

      if (message.type === "ready") {
        const style = getComputedStyle(document.documentElement);
        post({
          type: "init",
          settings: latest.current.value,
          language: latest.current.language,
          colors: Object.fromEntries(COLORS.map((name) => [name, style.getPropertyValue(name).trim()])),
        });
      } else if (message.type === "height" && typeof message.height === "number") {
        setHeight(Math.min(Math.max(40, Math.ceil(message.height)), MAX_HEIGHT));
      } else if (message.type === "change" && typeof message.settings === "object" && message.settings) {
        const { enabled, interval } = latest.current.value;
        latest.current.onChange({ ...(message.settings as ModuleSettings), enabled, interval });
      } else if (message.type === "command" && typeof message.action === "string") {
        const args = (typeof message.args === "object" && message.args ? message.args : {}) as Record<string, unknown>;
        void command(message.id, message.action, args);
      } else if (message.type === "open" && typeof message.url === "string" && /^https?:\/\//i.test(message.url)) {
        void openExternal(message.url);
      }
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [module, post]);

  return (
    <iframe
      ref={frame}
      className="plugin-settings-frame"
      title={plugin}
      sandbox="allow-scripts"
      src={images.pluginSettings(plugin, version)}
      style={{ height }}
    />
  );
}
