// Entry point for the standalone settings window (/settings.html), opened via
// the "popout" button in the dashboard. Reuses buildSettingsSheet in
// standalone mode — the panel fills the window and stays open. All changes go
// through the same /api/settings endpoints, so the live dashboard picks them
// up via its WebSocket / hot-reload as usual.

import { ThemeManager, buildSettingsSheet } from "./theme.js";
import { initI18n, t, onLanguageChange } from "./i18n.js";

async function bootstrap() {
  await initI18n();

  const theme = new ThemeManager();
  await theme.init();

  document.title = t("settings.dialog_label");
  onLanguageChange(() => {
    document.title = t("settings.dialog_label");
  });

  const sheet = buildSettingsSheet(theme, { standalone: true });
  await sheet.open();
}

bootstrap().catch((err) => {
  console.error("[settings-window] bootstrap failed:", err);
  document.body.textContent =
    "Settings failed to load — see console. / Einstellungen konnten nicht geladen werden — siehe Konsole.";
});
