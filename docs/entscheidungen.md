# Warum es so aussieht, wie es aussieht

Was in dieser Datei steht, ist nicht mehr Teil des Programms. Es sind
Entscheidungen, die getroffen wurden, damit niemand sie versehentlich
zurückdreht. Wie der Stand heute ist, steht in der [README](../README.de.md).

## Vom Chromium-Kiosk zum QML-Fenster

*31. August bis 1. September 2026*

Die Anzeige war ein Chromium im Kioskmodus, gestartet aus einem Shell-Skript,
und lud dieselbe Seite, die man auch im Browser aufrufen konnte.

Zwei Dinge sprachen dagegen.

**Das Fenster ließ sich nicht platzieren.** Chromium ist ein XWayland-Client.
KWin ignoriert die Geometrie, die ein solcher Client verlangt, und nach einem
Kaltstart landete das Fenster regelmäßig auf dem Hauptmonitor, weil der Xeneon
zu dem Zeitpunkt noch nicht eingerichtet war. Der Umweg dagegen war eine
erzeugte KWin-Regel mit fester Geometrie.

**Der Speicher wuchs.** Unter Wayland gab die Qt-WebEngine die Ebenen des
Compositors nicht wieder frei. Über mehrere Läufe am 31. August 2026 gemessen
waren es rund 20 MB je Minute. Bei einer Anzeige, die wochenlang durchläuft,
endet das im OOM-Killer.

Der Kiosk erzeugt das Fenster jetzt selbst, in Qt Quick. Damit weist er ihm
den Bildschirm direkt zu, statt einem fremden Prozess über eine Regel
vorzuschreiben, wohin er sich setzen soll. Es steht bei etwa 130 MB und bleibt
dort.

Die Gruppe `[edge-dashboard-kiosk]` in `~/.config/kwinrulesrc` gibt es
weiterhin, sie tut aber etwas anderes: sie hält das Fenster aus der
Fensterliste heraus, enthält keine Geometrie und wird von
`scripts/window-rule.sh` geschrieben. Ältere Installationen haben dort noch
die alten Geometrieschlüssel stehen; das Skript räumt sie beim nächsten Lauf
weg.

Ein Browser kommt nur noch für ein Video zurück, in einem eigenen Prozess, der
mit dem Video endet. Die systemweite Qt-WebEngine ist die Fassung mit den
Codecs, die YouTube abspielt.

## Kein Dashboard im Browser mehr

*1. September 2026*

Nach dem Umstieg auf QML gab es die Anzeige zweimal: einmal in QML für das
Display, einmal in JavaScript für den Browser. Beide mussten gepflegt werden,
jedes neue Widget zweimal gebaut.

Der Nutzen stand dazu in keinem Verhältnis. Das Backend lauscht auf
`127.0.0.1`, das Dashboard war also von genau dem Rechner erreichbar, auf dem
der Kiosk ohnehin läuft. Für ein zweites Gerät hätte man die Bind-Adresse
ändern müssen.

Gelöscht wurden `frontend/js/`, `index.html` und die Stilvorlagen `base.css`,
`widgets.css` und `fonts.css`, zusammen rund 5500 Zeilen. Der Server
beantwortet `/` seitdem mit 404.

Aus `frontend/` blieb, was Kiosk und Einstellungsfenster lesen:

* `css/themes/` und `locales/` liest der Kiosk direkt von der Platte
* `player.html` holt das Videofenster über HTTP
* `vendor/` liefert die Tabler-Symbole, die Schriften und den Emoji-Datensatz
  des Einstellungsfensters

Die JS-Dateien waren nebenbei die Registry des Layout-Editors: er listete, was
in `frontend/js/widgets/` lag, und las `static variants` per regulärem Ausdruck
aus dem Quelltext. Das ist jetzt ein Manifest je Widget in `widgets/`.

Die Schriften wurden vorher über `fonts.css` geladen. Das Kioskfenster hatte
dafür nie einen Ersatz, deshalb liefen `industrial`, `nightclub` und `toxic`
seit dem Umstieg auf einer Ersatzschrift. Der Kiosk lädt die Dateien aus
`vendor/fonts/` jetzt selbst beim Start.

## Sensoren werden über ihre Adresse angesprochen

*1. September 2026*

Eine Kachel des `sensor_focus`-Widgets speichert, welchen Messwert sie zeigt.
Diese id war `hwmon3/k10temp:1`, also der Verzeichnisname unter
`/sys/class/hwmon` plus Chipname und Nummer des Temperatureingangs.

Die hwmon-Nummer vergibt der Kernel beim Start in der Reihenfolge, in der sich
die Treiber melden. Sie ist damit für einen Lauf eindeutig, aber nicht über
Neustarts hinweg dieselbe. Bei drei NVMe-Laufwerken, die sich alle als `nvme`
melden, hätte eine Kachel danach ein anderes Laufwerk angezeigt.

Die id nennt jetzt die Adresse, an der die Hardware sitzt, aus dem
`device`-Verweis des hwmon-Eintrags: `k10temp@0000:00:18.3:1` für die CPU,
`spd5118@7-0051:1` für einen Speicherriegel. Ein PCI-Steckplatz und eine
i2c-Adresse ändern sich nicht, solange das Teil im selben Sockel steckt.
NVMe-Laufwerke verweisen auf ihre Controller-Nummer, die selbst wieder ein
Zähler ist, deshalb geht die Suche dort eine Ebene weiter bis zum Steckplatz.

Der Chipname bleibt Teil der id. Damit kann sie nur auf denselben Chip am
selben Ort passen, nie auf einen Nachbarn. Wo zwei Messwerte trotzdem
dieselbe id bekämen, hängt das Modul den hwmon-Slot an und schreibt eine
Warnung: diese beiden verlieren ihre Stabilität, aber keine Kachel zeigt einen
fremden Wert.

Alte ids passen auf nichts mehr. Betroffen ist nur die Sensorauswahl im
`sensor_focus`-Widget; sie wird einmal neu getroffen, und bis dahin sagt die
Kachel, dass der Sensor nicht mehr gemeldet wird.

---

[README](../README.de.md) · [English](decisions.md)
