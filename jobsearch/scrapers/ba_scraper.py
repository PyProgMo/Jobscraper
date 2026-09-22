"""Scraper für die öffentliche Jobsuche-API der Bundesagentur für Arbeit.

Nutzt dieselbe REST-API wie arbeitsagentur.de/jobsuche. Die API ist nicht
offiziell für Drittnutzung dokumentiert, aber weithin bekannt und stabil
(siehe z.B. github.com/bundesAPI/jobsuche-api). Der X-API-Key ist ein fest
vergebener, öffentlicher Client-Key der Jobbörse-Webseite selbst - keine
persönlichen Zugangsdaten nötig.

HINWEIS: Der Anbieter hat den Endpunkt von pc/v4/jobs auf pc/v6/jobs
umgestellt (v4 liefert seit 2026 nur noch 403); dabei haben sich auch die
Feldnamen der Antwort geändert (z.B. "ergebnisliste" statt
"stellenangebote", "stellenangebotsTitel" statt "titel"). Falls der
Anbieter erneut umstellt: einmal die Antwort mit
  curl -s -H "X-API-Key: jobboerse-jobsuche" \
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=Python&size=1"
ansehen und die Feldnamen unten in _parse_angebot() anpassen.
"""
import logging
import time
from typing import List

import requests

from ..schema import Job

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
API_KEY = "jobboerse-jobsuche"

log = logging.getLogger(__name__)


def _parse_angebot(a: dict) -> Job:
    lokationen = a.get("stellenlokationen") or []
    adresse = (lokationen[0].get("adresse") or {}) if lokationen else {}
    ort_str = ", ".join(filter(None, [adresse.get("ort"), adresse.get("region")]))
    refnr = a.get("referenznummer") or a.get("hashId") or a.get("id") or ""
    eintrittszeitraum = a.get("eintrittszeitraum") or {}

    return Job(
        title=(a.get("stellenangebotsTitel") or "").strip(),
        company=(a.get("firma") or "Unbekannt").strip(),
        location=ort_str or (adresse.get("ort") or ""),
        url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}" if refnr else "",
        source="ba",
        external_id=str(refnr) if refnr else f"{a.get('stellenangebotsTitel','')}-{a.get('firma','')}",
        description=a.get("stellenbeschreibung", "") or "",
        date_posted=(
            a.get("datumErsteVeroeffentlichung")
            or a.get("aenderungsdatum")
            or eintrittszeitraum.get("von")
            or ""
        ),
    )


def search(keyword: str, ort: str, umkreis_km: int, max_alter_tage: int, max_ergebnisse: int) -> List[Job]:
    jobs: List[Job] = []
    headers = {"X-API-Key": API_KEY}
    page = 1
    page_size = min(50, max_ergebnisse) or 50

    while len(jobs) < max_ergebnisse:
        params = {
            "was": keyword,
            "angebotsart": 1,  # 1 = Arbeit (keine Ausbildung/Praktikum)
            "veroeffentlichtseit": max_alter_tage,
            "page": page,
            "size": page_size,
        }
        if ort:
            params["wo"] = ort
            params["umkreis"] = umkreis_km

        try:
            resp = requests.get(BASE_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("BA-Suche fehlgeschlagen (%r / %r): %s", keyword, ort, exc)
            break
        except ValueError as exc:
            log.warning("BA-Antwort war kein gültiges JSON (%r / %r): %s", keyword, ort, exc)
            break

        angebote = data.get("ergebnisliste") or []
        if not angebote:
            break

        for a in angebote:
            jobs.append(_parse_angebot(a))
            if len(jobs) >= max_ergebnisse:
                break

        page += 1
        time.sleep(0.3)
        if page > 20:
            break

    return jobs


def search_all(keywords, orte, umkreis_km, max_alter_tage, max_ergebnisse) -> List[Job]:
    results: List[Job] = []
    for kw in keywords:
        for ort in orte:
            results.extend(search(kw, ort, umkreis_km, max_alter_tage, max_ergebnisse))
    return results
