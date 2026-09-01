# Ein Widget schreiben

Ein Widget besteht aus drei Dateien, die einander nie importieren:

* ein **Backend-Modul** in `backend/modules/`, das Daten erzeugt
* eine **Anzeige** in `shell/qml_kiosk/qml/widgets/`, die sie zeichnet
* ein **Manifest** in `widgets/`, das es dem Layout-Editor bekannt macht

Verbunden werden sie vom Hub. Er ruft jedes Modul auf dessen eigenem Takt auf
und schickt das Ergebnis über einen WebSocket; im Kiosk landet jeder Frame bei
den Widgets, die dieses Modul abonniert haben. Keine Seite weiß von der
anderen. Deshalb lässt sich eine Anzeige austauschen, ohne die Datenquelle
anzufassen, und ein Modul kann mehrere Widgets versorgen.

Ein Widget, das keine eigenen Daten braucht, kommt ohne Backend-Teil aus, so
wie Uhr und Pomodoro.

## Kurzfassung

```bash
# 1. die Quelle
$EDITOR backend/modules/mondphase.py
# 2. die Anzeige
$EDITOR shell/qml_kiosk/qml/widgets/Mondphase.qml
# 3. die Anmeldung
$EDITOR widgets/mondphase.json
# 4. einschalten und platzieren
$EDITOR config.yaml
systemctl --user restart edge-dashboard edge-kiosk
```

Alle drei werden über ihren Namen gefunden: das Modul meldet sich per
Dekorator an, das Manifest liegt unter seiner id, und die Anzeige heißt wie
die id in CamelCase.

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

Das ist ein vollständiges Modul. Was die Basisklasse sonst noch anbietet:

| | |
|---|---|
| `default_interval` | Sekunden zwischen den Aufrufen von `poll()`. Die Konfiguration kann es je Modul überschreiben. |
| `dedupe` | Standardmäßig `True`: eine unveränderte Antwort wird nicht erneut gesendet. Auf `False` setzen für Messreihen, wo eine Sparkline auch dann einen Frame braucht, wenn der Wert gleich bleibt. |
| `await self.emit(data)` | Sofort senden, außerhalb des Takts. Für Quellen, die sich von selbst melden, so wie das Medien-Modul bei MPRIS-Änderungen. Ein Modul darf `poll`, `emit` oder beides nutzen. |
| `settings_schema` | Felder, die das Einstellungsfenster für dieses Modul anbieten soll, siehe unten. |

Ein Fehler in `poll()` wird protokolliert und übersprungen, er reißt den Hub
nicht mit.

### Einstellbare Felder

`enabled` und `interval` bekommt jedes Modul ohne Zutun. Alles Weitere wird
deklariert, und das Fenster baut daraus die Eingabe:

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

## Die Anzeige

Die Anzeige ist eine QML-Datei in `shell/qml_kiosk/qml/widgets/`. Sie heißt
wie das Widget, in CamelCase: `mondphase` wird zu `Mondphase.qml`.

```qml
import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: root
    // Wird vom Fenster gesetzt, sobald das Widget geladen ist.
    property var theme
    // Welche Module ankommen. Leer, wenn das Widget keine Daten braucht.
    readonly property var moduleNames: ["mondphase"]
    // Was im Layout unter `options` steht, unverändert.
    property var options: ({})
    // Ist die Kachel als `compact` platziert?
    property bool compact: false

    property var payload: null

    // Wird für jeden Frame eines abonnierten Moduls gerufen. Bei mehreren
    // Einträgen in `moduleNames` sagt `module`, um welches es geht.
    function receive(module, data) {
        payload = data
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.mondphase.title")
            Layout.bottomMargin: Style.headingBottom
        }

        Text {
            text: root.payload ? Math.round(root.payload.fraction * 100) + "%" : "–"
            color: root.theme ? root.theme["accent"] : "#00e0ff"
            font.pixelSize: bridge.metrics.metric_size
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }

        Text {
            visible: !root.compact
            text: root.payload ? root.payload.days.toFixed(1) + " d" : "–"
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: Style.subSize
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }
    }
}
```

Der Vertrag ist klein:

* **`moduleNames`** bestimmt, was ankommt. Das Fenster stellt nur diese Frames
  zu, damit eine Kachel nicht bei jedem fremden Frame neu rechnet.
* **`receive(module, data)`** wird pro Frame gerufen. Beim Laden bekommt das
  Widget außerdem die zuletzt bekannte Antwort nachgereicht, damit es auf
  einem laufenden Kiosk nicht leer beginnt.
* **`theme`**, **`options`**, **`compact`** und **`confirm`** setzt das
  Fenster, sofern das Widget sie deklariert. `confirm` ist der gemeinsame
  Rückfrage-Dialog, `ask(text, knopf, gefährlich, callback)`.
* **`padH`** und **`padV`** sind der Innenabstand, den die Kachel nehmen soll.
  Ein Theme darf ihn überschreiben, solange die Kachel Platz dafür hat.

Das Aufräumen übernimmt QML: mit dem Objekt geht alles, was daran hängt.

Farben kommen aus `theme`, Maße aus dem Singleton `Style`, Texte aus
`bridge.tr(...)`. Für die üblichen Formen gibt es fertige Bausteine:
`Heading`, `Chart`, `MetricWidget`, `CoreBars` und `Confirm`.

Das Fenster findet die Datei über den Namen: `mondphase` wird zu
`Mondphase.qml`, `disk_usage` zu `DiskUsage.qml`. Die Regel steht in
`shell/qml_kiosk/views.py`. Findet sich keine Datei, zeigt die Kachel das an,
statt leer zu bleiben.

## Das Manifest

Erst durch `widgets/<name>.json` kennt der Layout-Editor das Widget. Dass die
Datei da ist, ist die Anmeldung; was drinsteht, ist freiwillig.

```json
{
  "modules": ["mondphase"],
  "variants": ["compact"]
}
```

`modules` wiederholt, was die Anzeige in `moduleNames` deklariert. Der Kiosk
liest es nicht, er richtet sich nach der QML-Datei; im Manifest steht es,
damit die Doku und die Anzeige gegeneinander geprüft werden können. Ein Test
schlägt an, wenn die beiden auseinanderlaufen.

### Varianten

`variants` bringt den Layout-Editor dazu, eine Auswahl statt eines Textfelds
zu zeigen. Die Variante erreicht das Widget als `compact`.

Die andere Darstellung wirklich bauen, nicht verstecken. `compact` lässt bei
den Messwert-Widgets das Diagramm über einen `Loader` ganz weg, statt es auf
`visible: false` zu setzen, denn ein verstecktes Diagramm hält weiter seine
Textur.

### Optionen

`options` beschreibt Felder, die im Layout-Editor unter der Kachel erscheinen,
im selben Format wie die Modul-Einstellungen (`SettingField`):

```json
{
  "modules": ["mondphase"],
  "options": [
    {
      "key": "show_days",
      "type": "bool",
      "label_key": "settings.widget.mondphase.show_days",
      "default": true
    }
  ]
}
```

Die Typen sind `bool`, `int`, `float`, `text`, `select`, `list` und `color`.
Ein `select` kann seine Werte vom Server erfragen, statt sie fest zu nennen:
`"options_source": "sensors"` füllt die Liste mit den aktuellen Sensoren und
setzt lesbare Beschriftungen dazu. Der Wert landet unverändert in `options`
des Widgets.

Gespeichert wird dabei die id eines Messwerts, etwa `k10temp@0000:00:18.3:1`.
Sie nennt den Chip und die Adresse, an der er sitzt, also den PCI-Steckplatz
oder die i2c-Adresse. Damit zeigt eine Kachel nach einem Neustart weiter auf
denselben Sensor, und sie kann nie auf einen anderen zeigen: der Chipname
gehört zur id. Findet sich die id nicht mehr, sagt das Widget das, statt einen
Nachbarwert anzuzeigen.

Ein fehlerhaftes Manifest kostet das Widget seine Varianten und Optionen und
schreibt eine Warnung. Das Widget bleibt in der Auswahl, der Editor läuft
weiter.

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

Die id unter `widgets` ist der Dateiname in `widgets/`, der Schlüssel unter
`modules` ist der `name` des Moduls. Platzieren geht bequemer
im Layout-Bereich des Einstellungsfensters, der dasselbe YAML schreibt.

Übersetzungen kommen nach `frontend/locales/de.json` und `en.json`. Die
Schlüssel sind flach und mit Punkten geschrieben, `{platzhalter}` ist die
Syntax zum Einsetzen.

## Worauf zu achten ist

**Nicht dauernd animieren.** Das ist der Fehler, der wehtut. Eine Fläche, die
sich ständig bewegt, kostet auf diesem Rechner rund 20 CPU-Punkte, unabhängig
davon, wie klein sie ist. Deshalb steht `Chart.travel` auf `false` und deshalb
zählt das Medien-Widget den Abspielkopf viermal je Sekunde weiter statt pro
Bild. Bewegung nur da, wo sie etwas erklärt.

**Bindungen statt Zuweisungen.** Ein Wert, der einmal zugewiesen wird,
ersetzt die Bindung und wird nie wieder aktualisiert. So zeigte das
GPU-Widget einmal für immer „GPU“ statt des Kartennamens, weil `text` in
`Component.onCompleted` gesetzt wurde.

**Listen nur neu aufbauen, wenn sich der Satz ändert**, nicht bei jedem Wert.
Ein `clear()` auf einem `ListModel` wirft die Delegates weg, setzt die
Scrollposition zurück und lädt Bilder neu. Das Sensoren-Widget vergleicht die
aneinandergehängten ids und schreibt sonst nur die Zahlen um.

**Nur die eigenen Module verarbeiten.** `moduleNames` sorgt dafür, dass
`receive` nicht bei jedem fremden Frame läuft. Ohne das rechnet jede Kachel
fünfmal je Sekunde für Daten, die einmal je Minute kommen.

**Farben ohne Prüfung sind ein Absturz.** Was aus der Konfiguration in eine
`color`-Eigenschaft geht, muss vorher gegen `#rgb`/`#rrggbb` geprüft werden;
`safeColour` in `QuickActions.qml` und `SensorFocus.qml` macht genau das.

**Kacheln sind breit und flach**, und die Anzeige wird berührt, nicht
geklickt. Ziele unter etwa 44 Pixeln sind darauf ärgerlich.

## Testen

```bash
uv run pytest tests/test_mondphase.py     # ein Modultest braucht keine Anzeige
/usr/lib/qt6/bin/qmllint -I shell/qml_kiosk/qml \
    shell/qml_kiosk/qml/widgets/Mondphase.qml
systemctl --user restart edge-kiosk
```

Modultests erzeugen die Klasse und warten auf `poll()`, Beispiele dafür stehen
reichlich in `tests/`. Für die Anzeige ist `qmllint` der schnelle erste
Durchgang; er findet Tippfehler und unbekannte Eigenschaften, bevor das
Fenster startet.

Wer nicht jedes Mal den echten Kiosk neu starten will, kann das Fenster
abseits des Displays rendern:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

Fehler in QML landen dabei auf der Standardfehlerausgabe. `--windowed` setzt
das Fenster auf den Hauptbildschirm statt auf den Xeneon.

---

[Ein Theme schreiben](themes.de.md) · [Warum es so aussieht](entscheidungen.md) · [README](../README.de.md) · [English](widgets.md)
