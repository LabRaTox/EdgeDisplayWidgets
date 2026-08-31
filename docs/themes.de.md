# Ein Theme schreiben

Ein Theme ist eine CSS-Datei in `frontend/css/themes/`. Datei ablegen, fertig:
das Backend listet das Verzeichnis, das Einstellungsfenster zeigt eine
Vorschau, indem es das Stylesheet tatsächlich lädt. Registrieren muss man
nirgends etwas.

```bash
cp frontend/css/themes/clean.css frontend/css/themes/meintheme.css
```

Auswählen unter **Design** im Einstellungsfenster, oder `default_theme:
meintheme` in der Konfiguration. Kein Neustart, die Anzeige wechselt, sobald
gespeichert ist.

## Was ein Theme ist

`base.css` definiert jede Variable zuerst mit einem funktionierenden Wert, das
Theme wird danach geladen. Ein Theme **überschreibt** also, es muss nicht
vollständig sein. Drei Zeilen sind ein gültiges Theme:

```css
:root {
  --bg: #101418;
  --fg: #e8eef4;
  --accent: #7dd3fc;
}
```

Alles andere behält die Werte aus `base.css`. Ein halbfertiges Theme sieht
deshalb unfertig aus, nicht kaputt.

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
| `--transition` | Dauer der eingebauten Übergänge (`220ms ease`) |

Zwei weitere sind freiwillig und werden nur von den Quick-Action-Kacheln
gelesen. Sie fallen auf eine Abstufung von `--card-bg` und auf `--fg` zurück,
weglassen ist also in Ordnung: `--qa-tile-bg` und `--qa-tile-fg`.

Ein Theme darf über Variablen hinausgehen. `cyberpunk.css` legt über
`body::after` Scanlines darüber, gibt `.widget h3` ein Leuchten und lässt ein
Widget beim Einblenden kurz flackern. Alles auf der Seite steht offen, die
Variablen sind nur der Teil, für den man das Markup nicht kennen muss.

## Worauf zu achten ist

**Kontrast bei schrägem Blick.** Der Xeneon Edge steht unterhalb der
Monitore, man schaut fast immer von oben darauf. `--fg-muted` mit 40 Prozent
Deckkraft liest sich frontal gut und verschwindet bei 30 Grad.

**Die Anzeige ist 2560x720.** Kacheln sind breit und flach. Ein Theme, das
vertikal Luft hinzufügt, nimmt sie den Diagrammen weg.

**Nichts dauerhaft animieren.** Ein pulsierender Rand oder ein wanderndes
Farbverlaufsmuster kostet auf diesem Rechner rund zwanzig CPU-Punkte,
durchgehend, für etwas, das aus einem Meter Entfernung niemand ansieht. Die
Animationen in `cyberpunk.css` laufen einmal beim Einblenden und hören dann
auf. Die Messwerte stehen im README.

**Beide Sprachen ansehen.** Deutsche Beschriftungen sind länger als
englische. Ein Theme, das die Kacheln enger stellt, fällt dort zuerst auf.

## Ausprobieren

```bash
systemctl --user restart edge-dashboard   # damit die neue Datei in der Liste auftaucht
```

Zum Arbeiten `http://127.0.0.1:8765/` im Browser öffnen, dann genügt nach
jeder Änderung ein Neuladen. `clean.css` ist das kürzeste Theme zum Lesen,
`cyberpunk.css` zeigt, wie weit man gehen kann.

---

[Ein Widget schreiben](widgets.de.md) · [README](../README.de.md) · [English](themes.md)
