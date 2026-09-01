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

---

[Ein Widget schreiben](widgets.de.md) · [Warum es so aussieht](entscheidungen.md) · [README](../README.de.md) · [English](themes.md)
