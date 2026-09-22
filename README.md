# Jobsuche – Automatisierung

Durchsucht täglich drei Quellen nach offenen Stellen, poolt und dedupliziert
die Treffer, bewertet jede Stelle mit einem Score 0–1000 nach Passung zu
deinem Profil, und vermeidet Doppelbewerbungen sowie zu viele gleichzeitige
Bewerbungen bei derselben Firma. Ergebnis: eine Liste offener Stellen,
beste Treffer zuerst.

## Aufbau

```
jobsuche/
  config.yaml          <- alle Einstellungen (Suchbegriffe, Orte, Gewichte, Limits)
  requirements.txt
  run_daily.py          <- headless, für den Cron-Job
  gui.py                <- Tkinter-Oberfläche mit 4 Reitern
  jobsearch/
    scrapers/
      ba_scraper.py      <- Bundesagentur für Arbeit (offizielle API)
      adzuna_scraper.py  <- Adzuna (offizielle API, braucht kostenlosen Key)
      web_scraper.py     <- Stepstone + Indeed (HTML-Scraping, fragil)
    dedupe.py            <- Fuzzy-Deduplizierung über Quellen hinweg
    scoring.py           <- Score 0-1000 nach Schlüsselwörtern
    tracker.py           <- Bewerbungslimits & "bereits beworben"
    storage.py
  tests/smoke_test.py    <- Selbsttest ohne Internet
  data/                  <- wird beim ersten Lauf angelegt (jobs_pool.json, applied.json)
  logs/                  <- wird beim ersten Lauf angelegt
```

Empfehlung: diesen Ordner als `Jobsuche/` neben deine bestehenden
`Anschreiben_Vorlage/`, `Lebenslauf/`, `Zeugnisse/`, `Bewerbungen/`-Ordner
unter `apply_with_claude/` legen. Der Standardpfad zum Bewerbungen-Ordner
in `config.yaml` (`../Bewerbungen`) passt dann automatisch.

## Installation

```bash
cd Jobsuche
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

`config.yaml` ist in `.gitignore` (kann also z.B. einen echten Adzuna-Key
enthalten, ohne versehentlich mitveröffentlicht zu werden) – `config.example.yaml`
ist die versionierte Vorlage ohne Geheimnisse.

Falls `tkinter` fehlt (Fehler `ModuleNotFoundError: No module named 'tkinter'`):

```bash
sudo apt install python3-tk
```

## Konfiguration (config.yaml)

- **Suchbegriffe & Orte** unter `suche` – frei anpassbar, du wolltest bewusst
  breit suchen, also gerne mehr Begriffe/Branchen ergänzen.
- **Adzuna-Key**: kostenlos auf https://developer.adzuna.com/ registrieren,
  `app_id`/`app_key` eintragen. Ohne gültigen Key wird die Quelle sauber
  übersprungen (kein Fehler).
- **Scoring-Gewichte** unter `scoring.keywords` – Treffer im Titel zählen
  doppelt. Erhöhe/senke Gewichte, um die Bewertung an dich anzupassen.
- **Bewerbungslimits** unter `bewerbungslimits.max_bewerbungen_pro_firma`
  (Standard: 2 gleichzeitige offene Bewerbungen pro Firma).

## Benutzung

**Oberfläche starten:**
```bash
python3 gui.py
```
Vier Reiter:
1. **Scraper** – Suche manuell anstoßen (einzeln oder alle Quellen), Live-Log.
2. **Pool & Sortierung** – Kennzahlen, "Neu bewerten" ohne neue Suche (nützlich
   nach Änderungen an den Scoring-Gewichten).
3. **Alle Stellen** – kompletter Pool, auch beworbene/limitierte Stellen.
4. **Ergebnis** – offene Treffer, **Score absteigend sortiert (beste Stelle
   oben)**. Doppelklick öffnet die Anzeige im Browser. Buttons zum Markieren
   als "beworben" oder "ignorieren", CSV-Export.

> Du hattest "aufsteigend" geschrieben – ich bin davon ausgegangen, dass du
> die besten Treffer oben sehen willst, also nach Score absteigend. Falls du
> tatsächlich die Reihenfolge umgedreht willst, in `gui.py` `reverse=True` zu
> `reverse=False` ändern (zwei Stellen, Suche nach `sort(key=lambda j: j.score`).

**Täglich per Cron laufen lassen** (ohne GUI):
```bash
crontab -e
# Jeden Morgen um 7 Uhr:
0 7 * * * cd /home/molin/Schreibtisch/apply_with_claude/Jobsuche && venv/bin/python run_daily.py >> logs/cron.log 2>&1
```
Die GUI zeigt danach automatisch die aktualisierten Daten an (liest dieselbe
`data/jobs_pool.json`).

**Selbsttest ohne Internet:**
```bash
python3 tests/smoke_test.py
```

## Wie "Bewerbungslimits" funktioniert

- Ein Button in der GUI ("Als beworben markieren") trägt die Stelle in
  `data/applied.json` ein – das ist die zuverlässige Quelle für "schon
  beworben" und für die Firmen-Obergrenze.
- Optional: trägst du in `config.yaml` unter `bewerbungslimits.firma_kuerzel`
  eine Zuordnung "Voller Firmenname: Kürzel" ein, wird zusätzlich dein
  bestehender `Bewerbungen/`-Ordner nach passenden Kürzeln durchsucht. Ein
  Treffer setzt nur einen weichen Hinweis (`moeglich_beworben`), damit
  keine echte Stelle durch eine falsche Zuordnung verloren geht.

## Wichtige Einschränkungen (bitte lesen)

- **Bundesagentur für Arbeit & Adzuna** nutzen offizielle/öffentliche APIs
  und sollten stabil laufen. Ich konnte die exakten Feldnamen der
  BA-API in dieser Sandbox aber nicht live gegen die echte API prüfen
  (kein Netzwerkzugriff auf arbeitsagentur.de von hier aus) – falls beim
  ersten echten Lauf Felder leer bleiben, steht im Kopf von
  `ba_scraper.py` ein `curl`-Befehl, mit dem du die Antwortstruktur prüfen
  und die Feldnamen in `_parse_angebot()` anpassen kannst.
- **Stepstone/Indeed-Scraping** ist absichtlich "best effort": beide Seiten
  ändern ihr HTML häufig und blocken Scraper zunehmend (Cloudflare/Captcha).
  Bricht dieser Teil weg, laufen BA und Adzuna unabhängig davon weiter.
  Bitte auch die Nutzungsbedingungen der Portale im Hinterkopf behalten –
  das Skript ist für deinen persönlichen Gebrauch gedacht und schickt nur
  wenige Anfragen mit Pausen dazwischen.
- Die komplette Pipeline (Dedupe, Scoring, Firmenlimits, Speichern) wurde
  hier mit synthetischen Testdaten und einem vollständigen Testlauf von
  `run_daily.py` geprüft und läuft fehlerfrei durch (`tests/smoke_test.py`).
  Die drei Scraper selbst konnten wegen der Netzwerk-Sandbox hier nicht
  gegen die echten Portale getestet werden – bitte beim ersten Lauf auf
  deinem Rechner kurz prüfen, ob Treffer ankommen.

## Lizenz

GNU General Public License v3.0 (GPLv3) – siehe [LICENSE](LICENSE). Frei
nutzbar, veränderbar und weiterverbreitbar; abgeleitete Werke müssen unter
derselben Lizenz offen bleiben. Ohne jede Gewährleistung (siehe
Lizenztext, Abschnitte 15–16) – insbesondere für das Stepstone/Indeed-
Scraping gilt: Nutzung auf eigene Verantwortung und im Rahmen der jeweiligen
Nutzungsbedingungen der Portale.
