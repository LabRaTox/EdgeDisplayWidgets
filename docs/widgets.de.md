# Ein Widget schreiben

Ein Widget besteht aus drei Dateien, die einander nie importieren:

* ein **Backend-Modul** in `backend/modules/`, das Daten erzeugt
* eine **Anzeige** in `shell/qml_kiosk/qml/widgets/`, die sie zeichnet
* ein **Manifest** in `widgets/`, das es dem Layout-Editor bekannt macht

Verbunden werden sie vom Hub. Er ruft jedes Modul auf dessen eigenem Takt
auf und schickt das Ergebnis über einen WebSocket; im Kiosk landet jeder Frame
bei den Widgets, die dieses Modul abonniert haben. Keine Seite weiß von der
anderen. Deshalb lässt sich eine Anzeige austauschen, ohne die Datenquelle
anzufassen, und ein Modul kann mehrere Widgets versorgen.

```text
poll() / emit() → Hub → {"module", "data", "ts"} → WebSocket → Bridge → receive(module, data)
```

Ein Widget, das keine eigenen Daten braucht, kommt ohne Backend-Teil aus, so
wie Uhr und Pomodoro: nur eine Anzeige und ein Manifest.

## Kurzfassung

```bash
# 1. die Quelle
$EDITOR backend/modules/mondphase.py
# 2. die Anzeige
$EDITOR shell/qml_kiosk/qml/widgets/Mondphase.qml
# 3. die Anmeldung
$EDITOR widgets/mondphase.json
# 4. einschalten und platzieren
$EDITOR config.local.yaml
systemctl --user restart edge-dashboard edge-kiosk
```

Alle drei werden über ihren Namen gefunden: das Modul meldet sich per
Dekorator an, das Manifest liegt unter seiner id, und die Anzeige heißt wie
die id in CamelCase. Platzieren lässt sich das Widget statt im Editor auch
im Einstellungsfenster, das dasselbe YAML schreibt. Welche Änderung welchen
Neustart braucht, steht in der Tabelle unter [Einbinden](#einbinden).

## Wie der Hub die Teile verbindet

Wer verstehen will, was sein Modul tut, liest am besten `backend/hub.py`. Der
Ablauf in Kürze:

1. **Entdecken.** Beim Start importiert der Hub jede Datei in
   `backend/modules/` (außer `base` und den mit Unterstrich beginnenden).
   Schon das Importieren lässt die `@register_module`-Dekoratoren laufen,
   dadurch füllt sich die Registry. Ein Modul, das beim Importieren scheitert,
   wird protokolliert und übersprungen; es reißt die anderen nicht mit.
2. **Instanziieren.** Für jeden in der Konfiguration aktivierten Block wird
   die zugehörige Klasse aus der Registry erzeugt und mit dem per
   `model_dump()` serialisierten Block übergeben. Danach bekommt das Modul
   über `bind()` die Möglichkeit, von sich aus zu senden.
3. **Takt.** Pro Modul läuft eine Aufgabe, die `poll()` im Abstand von
   `interval` aufruft, aber nie öfter als alle 50 Millisekunden, selbst wenn
   die Konfiguration weniger verlangt. Ein Fehler in `poll()` wird protokolliert,
   der nächste Takt kommt trotzdem.
4. **Senden.** Jede Antwort wandert als `{"module": name, "data": …, "ts": …}`
   an alle offenen Verbindungen, außer sie ist byteidentisch mit der
   vorherigen und das Modul hat `dedupe = True` (Standardeinstellung). Im
   Cache landet sie trotzdem, denn der Cache ist es, der einen frisch
   verbundenen Kiosk sofort versorgt.
5. **Nachreichen.** Ein Client, der sich verbindet, bekommt für jedes Modul
   die zuletzt bekannte Antwort. Dasselbe gilt innerhalb des Fensters: Ein
   Widget, das nachträglich geladen wird, etwa weil das Layout gerade
   gespeichert wurde, erhält die gecachten Werte über `bridge.cached()`
   nachgereicht und startet nie leer.
6. **Neuladen.** Speichert das Einstellungsfenster, werden die Module
   abgerissen und mit der neuen Konfiguration neu erzeugt; die Klassen
   werden dabei *nicht* neu importiert, die Registry bleibt, wie sie ist.
   Zusätzlich sendet der Hub einen Steuerframe `{"event": "settings", …}`,
   auf den der Kiosk seine Konfiguration neu liest und die Seiten neu baut.
   Module-Frames tragen einen `module`-Schlüssel, Steuerframes einen
   `event`-Schlüssel; die beiden kollidieren nie.

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

Das ist ein vollständiges Modul. Der Lebenslauf:

* `__init__(config)` bekommt den serialisierten Konfigurationsblock. Die
  Basisklasse liest daraus `interval`; alles andere liest das Modul selbst
  heraus, mit eigenen Defaults. `float(config.get("lat", 52.52))` im
  Wetter-Modul ist das Muster. Die Defaults müssen mit denen in der
  `settings_schema` übereinstimmen, sonst bietet das Fenster einen Wert an,
  der ein anderes Verhalten hat als ein unberührtes Feld.
* `setup()` läuft einmal vor dem ersten `poll()`. Schlägt es fehl, wird das
  protokolliert und das Modul übergangen; es wird nicht ständig erneut
  versucht.
* `poll()` ist die einzige abstrakte Methode und muss ein
  JSON-serialisierbares Wörterbuch zurückgeben. Blockierende Arbeit wie
  Dateien lesen oder psutil befragen gehört in `asyncio.to_thread(...)`, damit
  es nicht die gesamte Ereignisschleife anhält, wie es das Medien-Modul beim
  Lesen der Covers tut.
* `teardown()` läuft beim Neuladen und beim Beenden. Fehler darin werden
  protokolliert, der Rest läuft weiter.

Was die Basisklasse sonst noch anbietet:

| | |
|---|---|
| `default_interval` | Sekunden zwischen den Aufrufen von `poll()`, `1.0` wenn nichts angegeben. Die Konfiguration überschreibt es je Modul mit `interval`. |
| `dedupe` | Standardmäßig `True`: eine unveränderte Antwort wird nicht erneut gesendet. Auf `False` setzen für Messreihen, wo eine Sparkline auch dann einen Frame braucht, wenn der Wert gleich bleibt. Das gilt für `poll()` und `emit()` gleichermaßen. |
| `await self.emit(data)` | Sofort senden, außerhalb des Takts. Für Quellen, die sich von selbst melden, so wie das Medien-Modul bei MPRIS-Änderungen. Ein Modul darf `poll`, `emit` oder beides nutzen; `emit` ohne laufenden Hub (in Tests) ist ein No-op. |
| `settings_schema` | Felder, die das Einstellungsfenster für dieses Modul anbieten soll, siehe unten. |

### Zwei Robustheitsmuster

Ein Modul, das über HTTP, Sensoren oder D-Bus nach außen reicht, fällt
gelegentlich aus. Zwei Muster haben sich dafür eingebürgert, beide sind in
der Anzeige sichtbar:

* **`available`/`reason`** (Sensoren): Die Antwort trägt immer
  `{"available": false, "reason": "…"}`, wenn es gerade nichts zu lesen gibt,
  und die Anzeige zeigt die Begründung statt einer leeren Kachel.
* **`stale`** (Wetter): Ist die Abfrage gescheitert, aber eine alte Antwort
  da, wird die alte Antwort mit `stale: true` noch einmal gesendet. Das
  Widget zeigt weiter Werte an, statt bei einem kurzen Ausfall zu verschwinden.

### Einstellbare Felder

`enabled` und `interval` bekommt jedes Modul ohne Zutun. Alles Weitere wird
deklariert, und das Fenster baut daraus die Eingabe:

```python
import time
from typing import Any

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

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Derselbe Default wie in settings_schema, sonst verhält sich ein
        # unberührtes Feld anders als eines, das einmal gespeichert wurde.
        self.sueden = bool(config.get("suedhalbkugel", False))

    async def poll(self) -> dict[str, Any]:
        tage = (time.time() / 86400.0 - 6.0) % 29.53058867
        # Von Süden gesehen liegt die beleuchtete Seite links, also spiegelt
        # eine Anzeige, die die Scheibe zeichnet, sie bei gesetztem Feld.
        return {"fraction": tage / 29.53058867, "days": tage,
                "southern": self.sueden}
```

Die Felder im Einzelnen:

| | |
|---|---|
| `key` | Der Konfigurationsschlüssel, relativ zum Modulblock. Ein Punkt greift in verschachtelte Konfiguration (`govee.api_key`). |
| `type` | `bool`, `int`, `float`, `text`, `select`, `list` oder `color`. |
| `label_key` | Übersetzungsschlüssel für die Beschriftung, siehe unten. Fehlt der Eintrag, zeigt das Fenster den Schlüssel selbst. |
| `default` | Der Wert, den ein unberührtes Feld hat. Muss dem Default im Konstruktor entsprechen. |
| `help_key` | Optionale Erläuterung unter dem Feld. |
| `group_key` | Optionale Überschrift, unter der das Fenster Felder zusammenfasst. |
| `placeholder_key` | Optionaler Platzhaltertext für leere Eingaben. |
| `secret` | `True` maskiert den Wert in der API als `***`. Kommt das Feld unverändert maskiert zurück, bleibt der gespeicherte Wert erhalten. So wird ein API-Schlüssel nicht versehentlich mit `***` überschrieben. |
| `min`, `max`, `step` | Grenzen und Schrittweite für Zahlenfelder. |
| `options` | Die Werte eines `select`. |
| `option_label_keys` | Übersetzungsschlüssel zu einer festen `options`-Liste, eins zu eins. |
| `option_labels` | Bereits lesbare Namen zu einer zur Laufzeit ermittelten Liste; das Fenster übersetzt sie nicht noch einmal. |

**Ein neues Feld braucht einen Backend-Neustart.** Das Einstellungsfenster
holt die Feldliste vom laufenden Prozess (`/api/modules/schema`), und der Hub
importiert Modulcode nur beim Start; Neuladen erzeugt die Klassen neu, liest
aber keine neuen Dateien. Von Hand eingetragene unbekannte Schlüssel in der
Konfiguration sind erlaubt und werden an das Modul durchgereicht; das Fenster
bietet nur an, was es kennt.

### Nicht dauerhaft nachfragen

`interval` so groß zu wählen, wie es die Anzeige verträgt, gehört zum Design.
Die Mondphase braucht eine Abfrage pro Stunde, das Wetter zehn Minuten, und
CPU-Last sieht einmal je Sekunde nach. `dedupe` hilft zusätzlich: Ein Widget,
das seinen Zustand beschreibt, muss nicht bei jedem Takt einen Frame senden.

## Die Anzeige

Die Anzeige ist eine QML-Datei in `shell/qml_kiosk/qml/widgets/`. Sie heißt wie
das Widget, in CamelCase: `mondphase` wird zu `Mondphase.qml`. Die Regel
(`disk_usage` wird zu `DiskUsage.qml`, Unterstriche trennen die Wörter) steht
in `shell/qml_kiosk/views.py`; eine id, die nicht aus kleinen Buchstaben,
Ziffern und Unterstrichen besteht, wird gar nicht erst gesucht.

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
            // `show_days` hat den Default true; ausdrücklich abgeschaltet
            // muss es erst werden. Options kommen nur an, wenn sie im Layout
            // gesetzt wurden; ein Default im Manifest ist noch kein Wert.
            visible: !root.compact
                     && (root.options && root.options.show_days !== false)
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
  Widget zusätzlich die zuletzt bekannte Antwort nachgereicht, damit es auf
  einem laufenden Kiosk nicht leer beginnt.
* **`theme`** wird vom Fenster als Bindung gesetzt und folgt einem
  Themenwechsel von selbst. **`online`** (der Verbindungszustand, gebunden),
  **`compact`**, **`options`** und **`confirm`** setzt das Fenster, sofern
  das Widget sie deklariert. `confirm` ist der gemeinsame Rückfrage-Dialog,
  `ask(text, knopf, gefährlich, callback)`. Der Callback erhält `true` bei
  Bestätigung.
* **`padH`** und **`padV`** sind der Innenabstand, den die Kachel nehmen
  soll. Ohne Deklaration gelten die Maße des Themes. Ein Theme darf sie
  überschreiben, solange die Kachel Platz dafür hat.

Das Aufräumen übernimmt QML: mit dem Objekt geht alles, was daran hängt.

Findet sich zur id keine Datei, zeigt die Kachel das an („kein Widget: …“),
statt leer zu bleiben, damit ein Tippfehler in der id sichtbar bleibt. Eine
Kachel, die ganz ohne id gespeichert wurde, zeigt „Kachel ohne Widget“. Beide
Texte stehen in den Locale-Dateien (`kiosk.no_widget`,
`kiosk.tile_without_widget`).

### Farben, Maße, Texte

Farben kommen aus `theme`, Maße aus dem Singleton `Style`, Texte aus
`bridge.tr(...)`. Das Wörterbuch `theme` enthält die Variablen des aktiven
Themes als Zeichenketten; was ein Theme nicht setzt, fällt auf die
Grundwerte zurück. Die üblichen Schlüssel:

| | |
|---|---|
| `bg`, `fg`, `fg-muted` | Grundfläche, Vordergrund, abgeschwächter Text |
| `accent`, `accent-2` | Die beiden Akzentfarben |
| `ok`, `warn`, `bad` | Grün, Gelb, Rot für Zustände |
| `card-bg`, `card-border` | Kachelfläche und -rand |
| `gap` | Der Zeilenabstand der Seite, in Pixeln, als Zahl |
| `font-ui`, `font-mono`, `font-display` | Schriften für Text, Zahlen und große Figuren; je die erste Familie der CSS-Liste |

Was ein Theme an Größen und Verzierungen dazulegt, also Schriftgrößen der
Überschriften, Glow und Ecken, liegt nicht in `theme`, sondern in
`bridge.metrics` und `bridge.effects`, gefüllt von `shell/qml_kiosk/theme.py`.

Das Singleton `Style` (`shell/qml_kiosk/qml/Style.qml`) hält die Maße, die
in jedem Theme gleich sind: `headingBottom`, `subSize`, `subBottom`,
`axisSize`, `axisWidth`, `chartMinHeight`, `chartTicks`, die Maße der
Kernbalken und `pageGap`. Es ist in `shell/qml_kiosk/qml/qmldir`
angemeldet, ebenso der Singleton `Temperatures`; mit `import ".."` stehen
alle gemeinsamen Bausteine zur Verfügung.

### Was die Bridge anbietet

| | |
|---|---|
| `bridge.tr(key)` | Eine übersetzte Zeichenkette, der Schlüssel selbst, wenn die Übersetzung fehlt. Ein zweites Argument ist der Fallback. |
| `bridge.theme`, `bridge.metrics`, `bridge.effects` | Theme, Maße und Verzierungen, siehe oben. |
| `bridge.cached(module)` | Die zuletzt bekannte Antwort eines Moduls. |
| `bridge.iconUrl(icon, farbe)` | Eine zeichnbare Datei für ein Icon (`ti:…` Tabler, `app:…` Desktop-Symbol) oder `""` für Text und Emoji. |
| `bridge.api` | Die Basisadresse der REST-Endpunkte, für Widgets, die selbst lesen oder schreiben (Notizen, Schnellaktionen). |
| `bridge.online` | Ob der WebSocket gerade verbunden ist; das Fenster bindet es an Widgets, die `online` deklarieren. |
| `bridge.viewUrl(id)` | Die QML-Datei zu einer Widget-id; für die eigene Kachel braucht das niemand, aber es zeigt, wie das Fenster die Datei findet. |

### Fertige Bausteine

* **`Heading`**: die Kachelüberschrift, großgeschrieben, gesperrt, mit dem
  Glow des Themes.
* **`Chart`**: die Sparkline. Eigenschaften: `theme`, `series`
  (`[{ values: [...], color: c }]`), `maxValue`, `tickFormat` (eine
  Funktion), `samples` (Standard 60), `gapMs` (der gemessene Abstand zweier
  Samples) und `travel` (Standard `false`, siehe unten).
* **`MetricWidget`**: die Form, die CPU, GPU und RAM teilen. Überschrift,
  große Zahl daneben, Detailzeile darunter, Diagramm im Rest. Bei
  `compact` lässt es das Diagramm weg. Wer eine Messreihe zeigt, ruft nach
  jedem Frame `noteArrival()`, damit `Chart.gapMs` dem Modul-Takt folgt.
* **`CoreBars`**: die Balken je CPU-Kern, wie im CPU-Widget.
* **`Confirm`**: der Rückfrage-Dialog; das Widget deklariert `confirm` und
  bekommt ihn vom Fenster.
* **`Tile`**: die Kachel selbst, samt Innenabstand; ein Widget zeichnet
  normalerweise nicht selbst hinein.

`MetricWidget` und `Temperatures` sind Bausteine, keine Widgets. Sie haben
kein Manifest, und ein Test schlägt an, sollte je eines entstehen.

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
im selben Format wie die Modul-Einstellungen (`SettingField`), als JSON:

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
Ein `color` ist eine `#rrggbb`-Zeichenkette; leer bedeutet „was das Theme
verwendet“, deshalb bietet der Farbwähler ein Wegkreuzen an. Ein `select` kann
seine Werte vom Server erfragen, statt sie fest zu nennen:
`"options_source": "sensors"` füllt die Liste mit den aktuellen Sensoren und
setzt lesbare Beschriftungen dazu. Der Wert landet unverändert in `options`
des Widgets.

Gespeichert wird dabei die id eines Messwerts, etwa `k10temp@0000:00:18.3:1`.
Sie nennt den Chip und die Adresse, an der er sitzt, also den PCI-Steckplatz
oder die i2c-Adresse. Damit zeigt eine Kachel nach einem Neustart weiter auf
denselben Sensor, und sie kann nie auf einen anderen zeigen: der Chipname
gehört zur id. Die Liste beginnt mit einem leeren Eintrag, über den das Feld
wieder geleert wird. Findet sich die id nicht mehr, sagt das Widget das,
statt einen Nachbarwert anzuzeigen.

Ein fehlerhaftes Manifest schreibt eine Warnung und legt den Editor nie
lahm; das Widget bleibt in der Auswahl. Wie viel verloren geht, hängt vom
Schaden ab. Eine Datei, die kein gültiges JSON oder kein JSON-Objekt ist,
gilt als leer und verliert Varianten und Optionen. Eine lesbare Datei mit
ungültigem `options`-Block behält ihre Varianten und verliert nur die
Optionen, und ein einziges ungültiges Feld nimmt die ganze Liste mit.

## Einbinden

Es gibt zwei Konfigurationsdateien: `config.yaml` als Vorlage und
`config.local.yaml` als die eigene. Backend und Kiosk lesen jeweils genau
eine davon: `config.local.yaml`, wenn sie existiert, sonst `config.yaml`.
Zusammengeführt wird nichts, eine lokale Datei ersetzt die Vorlage also
vollständig. Nur die lokale schreibt das Einstellungsfenster, mit einer
`.bak`-Kopie des vorherigen Standes. Das Backend nimmt zusätzlich einen Pfad
aus `$EDGE_CONFIG` an (die Tests nutzen das); der Kiosk nicht, auf dem echten
Rechner bleibt die Variable deshalb ungesetzt. Eigene Änderungen gehören
in `config.local.yaml`.

```yaml
modules:
  mondphase:
    enabled: true
    interval: 3600
    # alle weiteren Schlüssel erhält das Modul unverändert

pages:
  - id: main
    grid:
      columns: "1fr 1fr 1fr"
      rows: "32px 1fr 1fr"
    widgets:
      - { id: mondphase, col: 3, row: 2, colspan: 1, rowspan: 1, variant: compact }
```

Die id unter `widgets` ist der Dateiname in `widgets/`, der Schlüssel unter
`modules` ist der `name` des Moduls. Spalten und Zeilen verstehen dieselbe
Spurliste: feste Pixelmaße (`32px`) und Anteile (`1fr`, `2fr`, auch
`minmax(0, 1fr)`, wovon nur der `fr`-Teil zählt). Feste Spuren behalten ihr
Maß, danach gehen die Abstände ab, und die Anteile teilen den Rest im
Verhältnis: `200px 1fr 2fr` ist eine 200 Pixel breite Spalte und zwei, die
sich den Rest eins zu zwei teilen. Alles andere, etwa `auto`, zählt als
`1fr`. Die Rechnung steht in `shell/qml_kiosk/grid.py`. Platzieren
geht bequemer im Layout-Bereich des Einstellungsfensters, der dasselbe YAML
schreibt.

Was wann einen Neustart braucht:

| Änderung | Greift nach |
|---|---|
| Layout, Optionen, `interval`, `enabled` | sofort; Speichern im Einstellungsfenster lädt den Hub neu und baut die Seiten neu auf |
| Neue QML-Datei | sobald die Kachel neu geladen wird. Ein Speichern im Layout-Editor genügt meist, sonst `systemctl --user restart edge-kiosk` |
| Geänderte QML-Datei | `systemctl --user restart edge-kiosk`; die QML-Engine hält eine geladene Datei im Cache, ein Speichern ersetzt sie nicht |
| Neues Modul, neue `settings_schema`, geänderter Modulcode | `systemctl --user restart edge-dashboard`; den Kiosk braucht es nur, wenn die Anzeige mitkam |

## Übersetzungen

Übersetzungen kommen nach `frontend/locales/de.json` und `en.json`. Die
Schlüssel sind flach und mit Punkten geschrieben, `{platzhalter}` ist die
Syntax zum Einsetzen. `bridge.tr` gibt bei einem fehlenden Eintrag den
Schlüssel selbst zurück, das Einstellungsfenster ebenso. Ein fehlender Text
fällt also nicht auf den Betrieb durch, bleibt aber sichtbar. Beide Sprachen
nachtragen, sonst zeigt das Fenster je Sprache unterschiedliche Reste.

## Worauf zu achten ist

**Nicht dauernd animieren.** Das ist der Fehler, der wehtut. Eine Fläche, die
sich ständig bewegt, kostet auf diesem Rechner rund 20 CPU-Punkte,
unabhängig davon, wie klein sie ist. Deshalb steht `Chart.travel` auf `false`
und deshalb zählt das Medien-Widget den Abspielkopf viermal je Sekunde weiter
statt pro Bild. Bewegung nur da, wo sie etwas erklärt.

**Bindungen statt Zuweisungen.** Ein Wert, der einmal zugewiesen wird,
ersetzt die Bindung und wird nie wieder aktualisiert. So zeigte das
GPU-Widget einmal für immer „GPU“ statt des Kartennamens, weil `text` in
`Component.onCompleted` gesetzt wurde. Wenn etwas nachträglich berechnet
werden muss: eine Hilfs-Eigenschaft deklarieren und darauf binden.

**Listen nur neu aufbauen, wenn sich der Satz ändert**, nicht bei jedem Wert.
Ein `clear()` auf einem `ListModel` wirft die Delegates weg, setzt die
Scrollposition zurück und lädt Bilder neu. Das YouTube-Widget hängt sich
`kind` und `id` aller Einträge zu einer Zeichenkette zusammen und baut die
Liste nur um, wenn die sich ändert; die Schnellaktionen tun mit `treeKey()`
dasselbe für ihren Ordnerbaum. (Das Sensoren-Widget baut seine Zeilen bei
jedem Frame neu, weil die Werte selbst im Modell liegen. Bei einer Tabelle
aus Zahlen ist das die Ausnahme, die man bewusst wählt.)

**Nur die eigenen Module verarbeiten.** `moduleNames` sorgt dafür, dass
`receive` nicht bei jedem fremden Frame läuft. Ohne das rechnet jede Kachel
fünfmal je Sekunde für Daten, die einmal je Minute kommen.

**Farben ohne Prüfung sind ein Absturz.** Was aus der Konfiguration in eine
`color`-Eigenschaft geht, muss vorher gegen `#rgb`/`#rrggbb` geprüft werden;
`safeColour` in `QuickActions.qml` und `SensorFocus.qml` macht genau das.
Leer ist das Ergebnis für alles, was kein Farbton ist, und die Anzeige fällt
auf die Farbe des Themes zurück, statt Qt mit einem ungültigen Wert
abstürzen zu lassen.

**Ein Zeichen für „kein Wert“.** Fehlende Werte sind ein einzelner
Gedankenstrich (`–`), nicht mehrere verschiedene Striche. Ein Test prüft
das über alle Anzeigen.

**Kacheln sind breit und flach**, und die Anzeige wird berührt, nicht
geklickt. Ziele unter etwa 44 Pixeln sind darauf ärgerlich.

## Testen und Debuggen

```bash
uv run pytest tests/test_mondphase.py     # ein Modultest braucht keine Anzeige
/usr/lib/qt6/bin/qmllint -I shell/qml_kiosk/qml \
    shell/qml_kiosk/qml/widgets/Mondphase.qml
systemctl --user restart edge-kiosk
```

Modultests erzeugen die Klasse und warten auf `poll()`; `asyncio`-Tests
laufen ohne Dekorator, die pytest-Konfiguration stellt den Modus automatisch
ein. Das Muster (Registry leeren, eigenes Modul anmelden, Antwort faken)
steht in `tests/test_weather.py`. Beispiele für alle Module liegen in
`tests/`. Für die Anzeige ist `qmllint` der schnelle erste Durchgang; er
findet Tippfehler und unbekannte Eigenschaften, bevor das Fenster startet.
Der Importpfad (`-I …`) ist nötig, damit er die gemeinsamen Bausteine und die
Singletons findet.

Wer nicht jedes Mal den echten Kiosk neu starten will, kann das Fenster
abseits des Displays rendern:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

`--windowed` öffnet ein normales Fenster in halber Größe auf dem
Hauptbildschirm, mit sichtbarem Zeiger. Ohne das Argument legt sich das
Fenster auf den Xeneon und versteckt den Zeiger. Fehler in QML landen dabei
auf der Standardfehlerausgabe.

Für die Frage „kommen die Daten überhaupt an?“ gibt es drei Anlaufstellen:

```bash
curl -s localhost:8765/api/snapshot | less    # letzter Frame je Modul
curl -s localhost:8765/api/widgets | less     # was der Layout-Editor sieht
curl -s localhost:8765/api/modules/schema | less
journalctl --user -u edge-dashboard -u edge-kiosk -f
```

Der Port steht unter `server.port`, Standard 8765. Der Snapshot zeigt, was
der Hub zuletzt gesendet hat. Steht dort ein Wert, ist das Modul in Ordnung
und die Anzeige der Ort, wo es klemmt.

## Vom Wunsch zum Widget: ein Kalender

Ein Kalender-Widget, als Checkliste durch die Abschnitte oben:

1. **Modul** `kalender`. Quelle kann eine Kalenderdatei, ein CalDAV-Server
   oder ein Skript sein. Termine ändern sich selten, also reicht
   `default_interval = 900`, und `dedupe` hält die Leitung dazwischen still.
   Die Felder `url` und `tage_voraus` kommen in die `settings_schema`. Für
   HTTP httpx mit Timeout nehmen (das Wetter-Modul nimmt 10 Sekunden) und im
   Fehlerfall das Muster `available`/`stale` verwenden.
2. **Antwort.** Klein und stabil halten, denn eine geänderte Form baut die
   Listen in der Anzeige neu auf:

   ```python
   {"available": True,
    "events": [{"title": "…", "start": "2026-10-12T09:00", "all_day": False}],
    "fetched_at": 1760000000.0}
   ```

3. **Anzeige** `Kalender.qml` mit `moduleNames: ["kalender"]`, eine Zeile je
   Termin.
4. **Manifest.** `{"modules": ["kalender"]}` genügt für den Anfang; eine
   Variante `compact` für eine kürzere Liste kann folgen.
5. **Texte und Tests.** Schlüssel in beide Locale-Dateien, ein Modultest mit
   einer festen Beispielantwort, `qmllint` für die Anzeige.

---

[Ein Theme schreiben](themes.de.md) · [Warum es so aussieht](entscheidungen.md) · [README](../README.de.md) · [English](widgets.md)
