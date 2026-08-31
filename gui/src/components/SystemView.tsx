import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api } from "../api/client";
import type { AutostartStatus } from "../types";

/**
 * Settings that live in the session rather than in the config file.
 *
 * The autostart switch writes systemd user units and enables them, which is
 * why it saves immediately instead of going through the SaveBar: there is no
 * draft to keep — either the units are enabled or they are not, and the
 * answer comes back from `systemctl`, not from our own state.
 */
export function SystemView() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<AutostartStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .autostart()
      .then((value) => {
        if (!cancelled) setStatus(value);
      })
      .catch((exc: unknown) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.setAutostart(enabled));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || status === null || !status.supported;

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("system.title")}</h2>
        <p>{t("system.help")}</p>
      </div>

      <div className="card">
        <div className="row">
          <label htmlFor="autostart">{t("system.autostart")}</label>
          <div className="control">
            <input
              id="autostart"
              type="checkbox"
              checked={status?.enabled ?? false}
              disabled={disabled}
              onChange={(e) => void toggle(e.target.checked)}
            />
            <div className="hint">{t("system.autostart_help")}</div>
            {status && !status.supported && (
              <div className="hint warn">{status.reason ?? t("system.unsupported")}</div>
            )}
            {error && <div className="hint warn">{error}</div>}
          </div>
        </div>

        {status && status.supported && (
          <div className="row">
            <label>{t("system.units")}</label>
            <div className="control">
              <div className="hint">
                {status.units.length > 0
                  ? status.units.join(", ")
                  : t("system.units_missing")}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
