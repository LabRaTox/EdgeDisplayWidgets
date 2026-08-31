import { useTranslation } from "react-i18next";

import type { SaveState } from "../lib/useDraft";

/**
 * The bar every editable view ends with. It stays visible while the view
 * scrolls, because a settings page you have to scroll to the bottom of to
 * find the save button is a settings page people forget to save.
 */
export function SaveBar({
  dirty,
  state,
  onSave,
  onReset,
  children,
}: {
  dirty: boolean;
  state: SaveState;
  onSave: () => void;
  onReset: () => void;
  children?: React.ReactNode;
}) {
  const { t } = useTranslation();

  let message: React.ReactNode = null;
  if (state.kind === "saving") message = <span className="state">{t("common.saving")}</span>;
  else if (state.kind === "saved" && !dirty)
    message = <span className="state ok">{t("common.saved")}</span>;
  else if (state.kind === "error")
    message = (
      <span className="state error">
        {t("common.failed_with_reason", { reason: state.message })}
      </span>
    );
  else if (dirty) message = <span className="state">{t("common.unsaved")}</span>;

  return (
    <div className="savebar">
      {children}
      <div className="spacer" />
      {message}
      <button className="btn" type="button" onClick={onReset} disabled={!dirty}>
        {t("common.reset")}
      </button>
      <button
        className="btn primary"
        type="button"
        onClick={onSave}
        disabled={!dirty || state.kind === "saving"}
      >
        {t("common.save")}
      </button>
    </div>
  );
}
