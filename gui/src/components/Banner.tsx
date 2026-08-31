import { useState } from "react";
import { useTranslation } from "react-i18next";

import { inApp, startDashboard, waitForBackend } from "../api/client";
import { useStore } from "../store";

/**
 * Shown while the backend cannot be reached.
 *
 * In the app it offers to start the services, because that is what an
 * unreachable backend almost always needs and this window can do it. In a
 * browser tab, where it cannot, it names the command instead: "not reachable"
 * without a next step is just a dead end.
 */
export function Banner() {
  const { t } = useTranslation();
  const online = useStore((s) => s.online);
  const error = useStore((s) => s.error);
  const starting = useStore((s) => s.starting);
  const load = useStore((s) => s.load);
  const [busy, setBusy] = useState(false);

  if (online) return null;

  const start = async () => {
    setBusy(true);
    try {
      await startDashboard();
      await waitForBackend();
      await load(true);
    } catch (exc) {
      console.warn("could not start the dashboard:", exc);
    } finally {
      setBusy(false);
    }
  };

  const working = busy || starting;

  return (
    <div className="banner">
      <div>
        <strong>{working ? t("status.starting") : t("status.offline")}</strong>
        <div className="hint">
          {working ? t("status.starting_hint") : (error ?? t("status.offline_hint"))}
        </div>
      </div>
      <div className="spacer" />
      {inApp() && (
        <button className="btn small" type="button" disabled={working} onClick={() => void start()}>
          {t("status.start_now")}
        </button>
      )}
      <button className="btn small" type="button" disabled={working} onClick={() => void load()}>
        {t("common.retry")}
      </button>
    </div>
  );
}
