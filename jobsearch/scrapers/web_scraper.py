"""Best-effort HTML-Scraper für Stepstone und Indeed.

WICHTIG: Beide Portale ändern ihr HTML regelmäßig und setzen zunehmend auf
Bot-Erkennung. Diese Scraper können jederzeit 0 Treffer liefern, ohne dass
etwas "kaputt" ist - das ist normal bei ungeschütztem Scraping kommerzieller
Jobportale und kein Grund zur Sorge, die Bundesagentur- und Adzuna-Quellen
laufen unabhängig davon weiter. Bitte die Nutzungsbedingungen der jeweiligen
Seite beachten; dieses Skript ist für den persönlichen, nicht-kommerziellen
Gebrauch gedacht, sendet nur wenige Anfragen mit Pausen dazwischen und
versucht keine Logins oder Schutzmaßnahmen zu umgehen.

Falls ein Scraper dauerhaft 0 Treffer liefert: im Browser die Such-URL öffnen,
"Element untersuchen" auf einer Ergebniskarte, und die CSS-Selektoren unten
entsprechend anpassen.
"""
import logging
import time
from typing import List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from ..schema import Job

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}


def _get(url: str, delay: float) -> str:
    time.sleep(delay)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def search_stepstone(keyword: str, ort: str, delay: float, max_ergebnisse: int) -> List[Job]:
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
            source="stepstone",
            external_id=href,
            description=card.get_text(" ", strip=True)[:500],
        ))

    return jobs


def search_indeed(keyword: str, ort: str, delay: float, max_ergebnisse: int) -> List[Job]:
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
            source="indeed",
            external_id=href,
            description=card.get_text(" ", strip=True)[:500],
        ))

    return jobs


def search_all(keywords, orte, stepstone_aktiv, indeed_aktiv, delay, max_ergebnisse) -> List[Job]:
    results: List[Job] = []
    for kw in keywords:
        for ort in orte:
            if stepstone_aktiv:
                results.extend(search_stepstone(kw, ort, delay, max_ergebnisse))
            if indeed_aktiv:
                results.extend(search_indeed(kw, ort, delay, max_ergebnisse))
    return results
