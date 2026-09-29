"""Best-effort HTML-Scraper für Stepstone.

WICHTIG: Stepstone ändert sein HTML regelmäßig und setzt zunehmend auf
Bot-Erkennung. Dieser Scraper kann jederzeit 0 Treffer liefern, ohne dass
etwas "kaputt" ist - das ist normal bei ungeschütztem Scraping kommerzieller
Jobportale und kein Grund zur Sorge, die übrigen Quellen laufen unabhängig
davon weiter. Bitte die Nutzungsbedingungen der Seite beachten; dieses
Skript ist für den persönlichen, nicht-kommerziellen Gebrauch gedacht,
sendet nur wenige Anfragen mit Pausen dazwischen und versucht keine Logins
oder Schutzmaßnahmen zu umgehen.

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

NAME = "stepstone"
ANZEIGENAME = "Stepstone"

log = logging.getLogger(__name__)


def ist_aktiv(cfg: dict) -> bool:
    return cfg["quellen"][NAME]["aktiv"]


def search(keyword: str, ort: str, delay: float, max_ergebnisse: int) -> List[Job]:
    jobs: List[Job] = []
    query = quote_plus(keyword)
    if ort:
        url = f"https://www.stepstone.de/jobs/{query}/in-{quote_plus(ort)}"
    else:
        url = f"https://www.stepstone.de/jobs/{query}"

    try:
        html = _get(url, delay)
    except requests.RequestException as exc:
        log.warning("Stepstone-Suche fehlgeschlagen (%r / %r): %s", keyword, ort, exc)
        return jobs

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('article[data-testid="job-item"]') or soup.select("article")

    for card in cards[:max_ergebnisse]:
        title_el = card.find(attrs={"data-at": "job-item-title"}) or card.find("h2")
        # Der Titel-Link führt zur konkreten Stelle. Der erste <a href> im
        # Card wäre stattdessen oft der Firmen-Logo-Link (data-at="company-logo"),
        # der auf die generische Jobübersicht der Firma zeigt - für alle
        # Stellen derselben Firma identisch und damit als external_id ungeeignet.
        link_el = title_el if title_el and title_el.name == "a" and title_el.has_attr("href") else None
        company_el = card.find(attrs={"data-at": "job-item-company-name"})
        location_el = card.find(attrs={"data-at": "job-item-location"})

        if not link_el or not title_el:
            continue

        href = link_el["href"]
        if href.startswith("/"):
            href = "https://www.stepstone.de" + href

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
