# Ein Widget schreiben

Ein Widget besteht aus zwei Dateien, die einander nie importieren:

* ein **Backend-Modul** in `backend/modules/`, das Daten erzeugt
* ein **Frontend-Widget** in `frontend/js/widgets/`, das sie zeichnet

Verbunden werden sie vom Hub. Er ruft jedes Modul auf dessen eigenem Takt auf
und schickt das Ergebnis über einen WebSocket; im Frontend landet jeder Frame
bei den Widgets, die dieses Modul abonniert haben. Keine Seite weiß von der
anderen. Deshalb lässt sich ein Widget austauschen, ohne die Datenquelle
anzufassen, und ein Modul kann mehrere Widgets versorgen.

Ein Widget, das keine eigenen Daten braucht, kommt ohne Backend-Hälfte aus, so
wie `clock.js` und `pomodoro.js`.

## Kurzfassung

```bash
# 1. die Quelle
$EDITOR backend/modules/mondphase.py
# 2. die Anzeige
$EDITOR frontend/js/widgets/mondphase.js
# 3. einschalten und platzieren
$EDITOR config.yaml
systemctl --user restart edge-dashboard
```

Beide Dateien werden über ihren Namen gefunden: das Modul meldet sich per
Dekorator an, die Widget-Datei wird über die id aus dem Layout importiert.

## Das Backend-Modul

```python
"""Mondphase, eine Zahl, einmal pro Stunde."""

from __future__ import annotations

import time
from typing import Any

from .base import Module, register_module


@register_module
class MoonPhaseModule(Module):
    name = "mondphase"          # Schlüssel in config.yaml, und was Widgets abonnieren
    default_interval = 3600.0   # Sekunden zwischen zwei Abfragen, per Config änderbar

    async def setup(self) -> None:
        """Einmal vor der ersten Abfrage. Hier Verbindungen öffnen."""

    async def poll(self) -> dict[str, Any]:
        """Auf dem Takt aufgerufen. Alles zurückgeben, was JSON transportiert."""
        tage = (time.time() / 86400.0 - 6.0) % 29.53058867
        return {"fraction": tage / 29.53058867, "days": tage}

    async def teardown(self) -> None:
        """Beim Neuladen und beim Beenden. Schließen, was setup geöffnet hat."""
```

Das ist ein vollständiges Modul. Was die Basisklasse darüber hinaus anbietet:

| | |
|---|---|
| `default_interval` | Sekunden zwischen den Aufrufen von `poll()`. Die Konfiguration kann es je Modul überschreiben. |
| `dedupe` | Standardmäßig `True`: eine unveränderte Antwort wird nicht erneut gesendet. Auf `False` setzen für Messreihen, wo eine Sparkline auch dann einen Frame braucht, wenn der Wert gleich bleibt. |
| `await self.emit(data)` | Sofort senden, außerhalb des Takts. Für Quellen, die sich von selbst melden, so wie das Medien-Modul bei MPRIS-Änderungen. Ein Modul darf `poll`, `emit` oder beides nutzen. |
| `settings_schema` | Felder, die das Einstellungsfenster für dieses Modul anbieten soll, siehe unten. |

Ein Fehler in `poll()` wird protokolliert und übersprungen, er reißt den Hub
nicht mit.

### Einstellbare Felder

`enabled` und `interval` bekommt jedes Modul ohne Zutun. Alles darüber hinaus
wird deklariert, und das Fenster baut daraus die Eingabe:

```python
from .base import Module, SettingField, register_module

@register_module
class MoonPhaseModule(Module):
    name = "mondphase"
    settings_schema = [
        SettingField(
            key="suedhalbkugel",
            type="bool",
            label_key="settings.mod.mondphase.suedhalbkugel",
            default=False,
        ),
    ]
```

`type` ist `bool`, `int`, `float`, `text`, `select` oder `list`. Ein `key` mit
Punkt greift in verschachtelte Konfiguration (`govee.api_key`). Mit
`secret=True` wird der Wert in der API maskiert, und ein unverändert
zurückgesendetes Feld behält den gespeicherten Wert. `label_key` und das
optionale `help_key` werden in `frontend/locales/*.json` nachgeschlagen, also
dort in beiden Sprachen ergänzen.

**Ein neues Feld braucht einen Backend-Neustart.** Das Konfigurationsmodell
weist unbekannte Schlüssel ab, ein Wert, den der laufende Prozess nicht kennt,
scheitert beim Speichern an der Validierung.

## Das Frontend-Widget

```js
import { registerWidget } from "../registry.js";
import { t } from "../i18n.js";

class MoonPhaseWidget {
  // Welche Module empfangen werden. Leer, wenn das Widget keine Daten braucht.
  static modules = ["mondphase"];
  // Freiwillig: die Darstellungen, die dieses Widget kennt. Der Layout-Editor
  // bietet genau diese an.
  static variants = ["compact"];

  mount(el, initial, ctx) {
    this.el = el;
    this.compact = ctx?.variant === "compact";
    el.innerHTML = `
      <div class="metric-head">
        <h3>${t("widget.mondphase.title")}</h3>
        <div class="metric-big" data-bind="phase">–</div>
      </div>
      ${this.compact ? "" : `<div class="metric-sub" data-bind="days">–</div>`}
    `;
    if (initial) this.update(initial);
  }

  update(data, moduleName, ts) {
    if (!data) return;
    this.el.querySelector('[data-bind="phase"]').textContent =
      `${Math.round(data.fraction * 100)}%`;
    if (this.compact) return;
    this.el.querySelector('[data-bind="days"]').textContent =
      `${data.days.toFixed(1)} d`;
  }

  destroy() {
    // Timer stoppen, Observer trennen, Sparklines abbauen. Wird aufgerufen,
    // wenn das Widget verschwindet oder die Seite nach einer Änderung neu
    // aufgebaut wird.
  }
}

registerWidget("mondphase", MoonPhaseWidget);
```

Die drei Methoden:

* **`mount(el, initial, ctx)`** baut das DOM einmal auf. `el` ist die Kachel,
  `initial` ist die zuletzt bekannte Antwort, falls es eine gibt, damit ein
  Widget auf einem laufenden Dashboard nicht leer beginnt. `ctx` enthält
  `{id, variant, options}`.
* **`update(data, moduleName, ts)`** wird pro Frame aufgerufen. Bei mehreren
  Einträgen in `static modules` sagt `moduleName`, um welches es geht.
* **`destroy()`** muss zurücknehmen, was `mount` aufgebaut hat. Ein
  verschobenes Widget wird abgebaut und neu aufgebaut.

### Varianten

`static variants = ["compact"]` bringt den Layout-Editor dazu, eine Auswahl
statt eines Textfelds zu zeigen: das Backend liest diese Zeile beim Scannen
des Verzeichnisses aus der Datei. Die Variante erreicht das Widget als
`ctx.variant`, und `data-variant` steht auf der Kachel, damit auch CSS darauf
zugreifen kann.

Die andere Darstellung wirklich bauen, nicht verstecken. `compact` lässt bei
den Messwert-Widgets das Diagramm aus dem DOM, statt es auf `display: none`
zu setzen, denn eine versteckte Sparkline zeichnet bei jedem Messwert weiter.

### Optionen

Was im Layout unter `options` steht, erreicht `ctx.options` unverändert. Der
Platz für Einstellungen einer einzelnen Instanz, die kein Schema wert sind, so
wie die Uhr `options: { show_seconds: true }` nimmt.

## Einbinden

```yaml
modules:
  mondphase:
    enabled: true
    interval: 3600

pages:
  - id: main
    grid:
      columns: "1fr 1fr 1fr"
      rows: "32px 1fr 1fr"
    widgets:
      - { id: mondphase, col: 3, row: 2, variant: compact }
```

Die id unter `widgets` ist der Dateiname in `frontend/js/widgets/`, der
Schlüssel unter `modules` ist der `name` des Moduls. Platzieren geht bequemer
im Layout-Bereich des Einstellungsfensters, der dasselbe YAML schreibt.

Übersetzungen kommen nach `frontend/locales/de.json` und `en.json`. Die
Schlüssel sind flach und mit Punkten geschrieben, `{platzhalter}` ist die
Syntax zum Einsetzen.

## Worauf zu achten ist

**Nicht pro Frame animieren.** Das ist der Fehler, der wehtut. 32 CPU-Kerne
in JavaScript zu interpolieren kostete auf diesem Rechner 29 CPU-Punkte, für
Balken, die `transition: height 200ms` in CSS ohnehin schon bewegt hat. Ein
Schreibvorgang pro Messwert, das Bewegen macht CSS.

**Nur schreiben, wenn sich etwas geändert hat.** `update()` läuft so oft, wie
das Modul abfragt. Die Knoten in `mount()` merken statt sie jedes Mal neu zu
suchen, und den Schreibvorgang auslassen, wenn der Text derselbe ist.

**Listen nur neu aufbauen, wenn sich der Satz ändert**, nicht bei jedem Wert.
Das Sensoren-Widget vergleicht die aneinandergehängten ids und schreibt sonst
nur die Zahlen um.

**Alles von außen maskieren.** Was aus einer Antwort in `innerHTML` landet,
muss maskiert werden; in `disk_usage.js` stehen die zwei Hilfsfunktionen
dafür. Für Werte in einem Attribut gilt dasselbe.

**Kacheln sind breit und flach**, und die Anzeige wird berührt, nicht
geklickt. Ziele unter etwa 44 Pixeln sind darauf ärgerlich.

## Testen

```bash
uv run pytest tests/test_mondphase.py     # ein Modultest braucht keine Anzeige
uv run python -m backend.main             # dann http://127.0.0.1:8765 öffnen
```

Modultests erzeugen die Klasse und warten auf `poll()`, Beispiele dafür stehen
reichlich in `tests/`. Fürs Frontend ist der Browser der schnellere Weg: der
Kiosk hat keine Entwicklerwerkzeuge, dieselbe Seite bekommt aber jeder
Browser, und ein Neuladen zieht eine geänderte Widget-Datei.

---

[Ein Theme schreiben](themes.de.md) · [README](../README.de.md) · [English](widgets.md)
