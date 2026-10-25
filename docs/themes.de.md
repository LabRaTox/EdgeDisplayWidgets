# Ein Theme schreiben

Ein Theme ist eine CSS-Datei in `frontend/css/themes/`. Die Datei in diesem
Verzeichnis ist die Anmeldung: das Backend listet sie, und das
Einstellungsfenster zeigt eine Vorschau, indem es das Stylesheet lädt.

```bash
cp frontend/css/themes/clean.css frontend/css/themes/meintheme.css
```

Auswählen unter **Design** im Einstellungsfenster, oder `default_theme:
meintheme` in der Konfiguration. Kein Neustart, die Anzeige wechselt, sobald
gespeichert ist.

## Was ein Theme ist

Für jede Variable gibt es einen funktionierenden Grundwert, das Theme wird
darüber gelegt. Ein Theme **überschreibt** also, es muss nicht vollständig
sein. Drei Zeilen sind ein gültiges Theme:

```css
:root {
  --bg: #101418;
  --fg: #e8eef4;
  --accent: #7dd3fc;
}
```

Alles andere behält seinen Grundwert; die Liste steht als `BASE` in
`shell/qml_kiosk/theme.py`. Ein halbfertiges Theme sieht deshalb unfertig aus,
nicht kaputt.

## Die Variablen

| Variable | Was sie färbt |
|---|---|
| `--bg` | die Fläche hinter allem |
| `--fg` | normaler Text |
| `--fg-muted` | Beschriftungen, Einheiten, zweite Zeilen |
| `--accent` | die große Zahl eines Widgets, aktive Zustände, Sparklines |
| `--accent-2` | die zweite Kurve, wo es zwei gibt (Upload im Netzwerk-Widget) |
| `--ok` `--warn` `--bad` | Zustände: verbunden, Warnung, kritisch |
| `--card-bg` | die Fläche einer Widget-Kachel |
| `--card-border` | deren Rand |
| `--font-ui` | Bedienelemente und Fließtext |
| `--font-mono` | Zahlen, alles was beim Zählen nicht springen soll |
| `--font-display` | die großen Ziffern |
| `--gap` | Abstand zwischen den Kacheln (`8px`) |

Ein Theme darf über Variablen hinausgehen, aber nur ein Teil davon kommt auf
der Anzeige an: der Kiosk rendert kein CSS, er liest die Datei. Gelesen werden
Innenabstand, Eckenradius, Hintergrund und die abgeschnittene Ecke von
`.widget`, Größe, Gewicht, Laufweite, Farbe und Textschatten von
`.widget h3`, das Schriftgewicht von `.clock-time`, der Schatten von
`.metric-big` sowie die Scanlines, die ein Theme mit
`repeating-linear-gradient` über die Seite legt.

Alles Weitere bleibt der Browser-Darstellung vorbehalten und hat auf dem
Display keine Wirkung, etwa Animationen oder mit Pseudo-Elementen gezeichnete
Verzierungen. Was genau gelesen wird, steht in `shell/qml_kiosk/theme.py`.

## Worauf zu achten ist

**Kontrast bei schrägem Blick.** Der Xeneon Edge steht unterhalb der
Monitore, man schaut fast immer von oben darauf. `--fg-muted` mit 40 Prozent
Deckkraft liest sich frontal gut und verschwindet bei 30 Grad.

**Die Anzeige ist 2560x720.** Kacheln sind breit und flach. Ein Theme, das
vertikal Luft hinzufügt, nimmt sie den Diagrammen weg.

**Animationen bleiben in der Datei.** Der Kiosk setzt keine um, ein
pulsierender Rand bewegt sich auf dem Display also nicht. Das ist Absicht:
eine Fläche, die sich dauernd bewegt, kostet auf diesem Rechner rund zwanzig
CPU-Punkte, für etwas, das aus einem Meter Entfernung niemand ansieht.

**Beide Sprachen ansehen.** Deutsche Beschriftungen sind länger als
englische. Ein Theme, das die Kacheln enger stellt, fällt dort zuerst auf.

## Ausprobieren

```bash
systemctl --user restart edge-dashboard   # damit die neue Datei in der Liste auftaucht
systemctl --user restart edge-kiosk       # nach jeder Änderung an der Datei
```

Das Design wird beim Start gelesen, ein Neustart des Kiosks zeigt also die
Änderung. Wer nicht jedes Mal das Display umschalten will, rendert das Fenster
daneben:

```bash
cd shell
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m qml_kiosk.main --windowed
```

`clean.css` ist das kürzeste Theme zum Lesen, `cyberpunk.css` zeigt, wie weit
man gehen kann.

Bleibt eine Änderung wirkungslos, hilft die Liste oben: nur ein Teil einer
Stilvorlage kommt auf der Anzeige an.

## Ein Theme für den Store

Ein Theme lässt sich über den Plugin-Store verteilen wie ein Widget. Es liegt
dann in einem eigenen Ordner und bringt sein Stylesheet mit, optional die
Schriften, die es nennt. Ein Beispiel steht in `examples/plugins/mint-night/`.

```text
mint-night/
  manifest.json
  theme.css       dasselbe Format wie die Dateien in frontend/css/themes/
  fonts/*.ttf     optional, auch .otf und .woff2
```

```json
{
  "app": "edgedash",
  "type": "theme",
  "id": "mint-night",
  "version": "1.0.0",
  "name": { "de": "Mintnacht", "en": "Mint night" },
  "summary": { "de": "…", "en": "…" },
  "license": "MIT",
  "css": "theme.css"
}
```

* **`type: theme`** unterscheidet es von einem Widget. Ein Theme bringt kein
  Modul mit; der Store lehnt eines mit `module` ab, und Edge Dash installiert
  es nicht.
* **`id`** ist der Name, unter dem das Theme in der Konfiguration steht
  (`default_theme: mint-night`). Die Namen der mitgelieferten Themes sind im
  Store reserviert.
* **`css`** nennt das Stylesheet, ohne Angabe `theme.css`.

Installiert und entfernt wird unter **Plugins → Designs**, ausgewählt unter
**Design**. Wird das aktive Theme entfernt, wechselt die Anzeige zu `clean`.
Schriften aus `fonts/` meldet der Kiosk an, sobald das Theme gewählt wird.
Für den Kiosk gelten dieselben Regeln wie oben: Er liest die Variablen und
die Regeln aus der Liste, alles andere im Stylesheet bleibt ohne Wirkung.

---

[Ein Widget schreiben](widgets.de.md) · [Warum es so aussieht](entscheidungen.md) · [README](../README.de.md) · [English](themes.md)
