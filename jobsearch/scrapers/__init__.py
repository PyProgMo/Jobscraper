"""Bündelt den Zugriff auf alle einzelnen Quellen-Scraper.

Jede durchsuchte Website/API hat ihr eigenes Modul in diesem Paket
(ba_scraper.py, arbeitnow_scraper.py, adzuna_scraper.py, stepstone_scraper.py,
indeed_scraper.py). Damit gui.py und run_daily.py nicht für jede Quelle
eigenen, fast identischen Code brauchen, stellt jedes dieser Module dieselbe
kleine Schnittstelle bereit:

    NAME          - Schlüssel in config.yaml unter 'quellen.<NAME>'
    ANZEIGENAME   - Name für Log-Meldungen/Buttons ("Bundesagentur für Arbeit")
    ist_aktiv(cfg) -> bool
    search_all(cfg) -> List[Job]

scrape() unten ruft alle angefragten, aktiven Quellen einheitlich auf.

Neue Quelle hinzufügen: neues Modul hier im Paket anlegen, das diese vier
Namen bereitstellt (siehe z.B. arbeitnow_scraper.py als einfachstes
Beispiel), unten in ALLE eintragen, und einen Abschnitt 'quellen.<NAME>' in
config.yaml/config.example.yaml ergänzen. gui.py und run_daily.py brauchen
dafür keine Änderung.
"""
from typing import Callable, List, Optional

from . import adzuna_scraper, arbeitnow_scraper, ba_scraper, indeed_scraper, stepstone_scraper
from ..schema import Job

# Reihenfolge = Reihenfolge der Buttons in der GUI.
ALLE = [ba_scraper, arbeitnow_scraper, adzuna_scraper, stepstone_scraper, indeed_scraper]
NAMEN = [modul.NAME for modul in ALLE]


def scrape(quellen_namen, cfg: dict, log: Optional[Callable[[str], None]] = None) -> List[Job]:
    """Durchsucht alle Module aus ALLE, deren NAME in quellen_namen steht und
    die in config.yaml aktiv sind. log() bekommt Fortschrittsmeldungen
    ("X wird durchsucht...", "-> N Treffer."), z.B. gui.py's Log-Anzeige oder
    logging.info bei run_daily.py. Ohne log-Parameter laufen die Meldungen
    ins Leere."""
    log = log or (lambda msg: None)
    ergebnisse: List[Job] = []
    for modul in ALLE:
        if modul.NAME not in quellen_namen:
            continue
        if not modul.ist_aktiv(cfg):
            continue
        log(f"{modul.ANZEIGENAME} wird durchsucht...")
        treffer = modul.search_all(cfg)
        ergebnisse.extend(treffer)
        log(f"  -> {len(treffer)} Treffer.")
    return ergebnisse
