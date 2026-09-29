"""Best-effort HTML-Scraper für Indeed.

WICHTIG: Indeed ändert sein HTML regelmäßig und setzt zunehmend auf
Bot-Erkennung (aktuell praktisch immer ein 403 ohne echten Browser). Dieser
Scraper kann jederzeit 0 Treffer liefern, ohne dass etwas "kaputt" ist - das
ist normal bei ungeschütztem Scraping kommerzieller Jobportale und kein
Grund zur Sorge, die übrigen Quellen laufen unabhängig davon weiter. Bitte
die Nutzungsbedingungen der Seite beachten; dieses Skript ist für den
persönlichen, nicht-kommerziellen Gebrauch gedacht, sendet nur wenige
Anfragen mit Pausen dazwischen und versucht keine Logins oder
Schutzmaßnahmen zu umgehen.

Falls dauerhaft 0 Treffer: im Browser die Such-URL öffnen, "Element
untersuchen" auf einer Ergebniskarte, und die CSS-Selektoren unten
entsprechend anpassen.
"""
import logging
from typing import List
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
import requests

from ..schema import Job
from ._http import get as _get

NAME = "indeed"
ANZEIGENAME = "Indeed"

log = logging.getLogger(__name__)


def ist_aktiv(cfg: dict) -> bool:
    return cfg["quellen"][NAME]["aktiv"]


def search(keyword: str, ort: str, delay: float, max_ergebnisse: int) -> List[Job]:
    jobs: List[Job] = []
    q = quote_plus(keyword)
    l = quote_plus(ort) if ort else ""
    url = f"https://de.indeed.com/jobs?q={q}&l={l}"

    try:
        html = _get(url, delay)
    except requests.RequestException as exc:
        log.warning("Indeed-Suche fehlgeschlagen (%r / %r): %s", keyword, ort, exc)
        return jobs

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.job_seen_beacon") or soup.select("div.jobsearch-SerpJobCard")

    for card in cards[:max_ergebnisse]:
        title_el = card.select_one("h2.jobTitle span") or card.select_one("h2.jobTitle")
        company_el = card.select_one("span.companyName")
        location_el = card.select_one("div.companyLocation")
        # Link innerhalb der Titel-Überschrift statt des ersten <a> im Card:
        # Karten können weitere Links (z.B. zum Firmenprofil) vor dem
        # Titel-Link enthalten, die sonst fälschlich als external_id landen.
        link_el = card.select_one("h2.jobTitle a[href]") or card.select_one("a[href]")

        if not title_el or not link_el:
            continue

        href = link_el["href"]
        if href.startswith("/"):
            href = "https://de.indeed.com" + href

        jobs.append(Job(
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True) if company_el else "Unbekannt",
            location=location_el.get_text(strip=True) if location_el else ort,
            url=href,
            source=NAME,
            external_id=href,
            description=card.get_text(" ", strip=True)[:500],
        ))

    return jobs


def search_all(cfg: dict) -> List[Job]:
    suche = cfg["suche"]
    delay = cfg["quellen"][NAME]["request_delay_sekunden"]
    ergebnisse: List[Job] = []
    for kw in suche["keywords"]:
        for ort in suche["orte"]:
            ergebnisse.extend(search(kw, ort, delay, suche["ergebnisse_pro_quelle"]))
    return ergebnisse
