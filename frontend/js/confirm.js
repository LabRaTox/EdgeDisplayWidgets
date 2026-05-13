// Themed confirm/alert dialog. Returns a Promise<boolean>.
//
// Singleton DOM — the overlay is built once on first use and reused for
// every subsequent call, so concurrent calls would clobber each other.
// That's by design: a confirm prompt is modal and exclusive.

import { t } from "./i18n.js";

let _root = null;

function ensure() {
  if (_root) return _root;
  const root = document.createElement("div");
  root.id = "ui-confirm";
  root.hidden = true;
  root.innerHTML = `
    <div class="ui-confirm-backdrop"></div>
    <div class="ui-confirm-panel" role="dialog" aria-modal="true">
      <div class="ui-confirm-message" data-bind="message"></div>
      <div class="ui-confirm-actions">
        <button type="button" class="ui-confirm-btn ui-confirm-cancel" data-act="cancel"></button>
        <button type="button" class="ui-confirm-btn ui-confirm-ok" data-act="ok"></button>
      </div>
    </div>
  `;
  document.body.appendChild(root);
  _root = root;
  return root;
}

/**
 * Show a themed confirm dialog.
 *
 * @param {string} message  Question to display.
 * @param {object} [opts]
 * @param {string} [opts.okLabel]      Label of the confirm button.
 * @param {string} [opts.cancelLabel]  Label of the cancel button.
 * @param {boolean} [opts.danger]      Style the OK button as destructive (red).
 * @returns {Promise<boolean>} `true` if confirmed, `false` if cancelled.
 */
export function confirmDialog(message, opts = {}) {
  const root = ensure();
  const okLabel = opts.okLabel || t("common.confirm");
  const cancelLabel = opts.cancelLabel || t("common.cancel");
  const danger = !!opts.danger;

  return new Promise((resolve) => {
    const okBtn = root.querySelector('[data-act="ok"]');
    const cancelBtn = root.querySelector('[data-act="cancel"]');
    const backdrop = root.querySelector(".ui-confirm-backdrop");
    root.querySelector('[data-bind="message"]').textContent = message;
    okBtn.textContent = okLabel;
    cancelBtn.textContent = cancelLabel;
    okBtn.classList.toggle("is-danger", danger);

    const close = (result) => {
      root.classList.remove("is-open");
      // The closing transition runs out before we hide; hiding too early
      // makes the panel snap rather than fade.
      setTimeout(() => {
        root.hidden = true;
      }, 180);
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      backdrop.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => close(true);
    const onCancel = () => close(false);
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Enter") {
        e.preventDefault();
        onOk();
      }
    };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    backdrop.addEventListener("click", onCancel);
    document.addEventListener("keydown", onKey);

    root.hidden = false;
    requestAnimationFrame(() => {
      root.classList.add("is-open");
      okBtn.focus();
    });
  });
}
