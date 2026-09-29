"""Scraper für die offizielle Adzuna Jobs-API (https://developer.adzuna.com/).
Benötigt kostenlose app_id + app_key (Registrierung auf developer.adzuna.com),
in config.yaml unter quellen.adzuna eintragen. Ohne gültige Zugangsdaten wird
diese Quelle übersprungen, statt einen Fehler zu werfen.
"""
import logging
from typing import List

import requests

from ..schema import Job

NAME = "adzuna"
ANZEIGENAME = "Adzuna"

log = logging.getLogger(__name__)


def ist_aktiv(cfg: dict) -> bool:
    return cfg["quellen"][NAME]["aktiv"]


def search(keyword: str, ort: str, app_id: str, app_key: str, land: str,
           max_alter_tage: int, max_ergebnisse: int) -> List[Job]:
    jobs: List[Job] = []
    page = 1
    per_page = min(50, max_ergebnisse) or 50

    while len(jobs) < max_ergebnisse:
        url = f"https://api.adzuna.com/v1/api/jobs/{land}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": keyword,
            "max_days_old": max_alter_tage,
            "results_per_page": per_page,
            "content-type": "application/json",
        }
        if ort:
            params["where"] = ort

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("Adzuna-Suche fehlgeschlagen (%r / %r): %s", keyword, ort, exc)
            break
        except ValueError as exc:
            log.warning("Adzuna-Antwort war kein gültiges JSON (%r / %r): %s", keyword, ort, exc)
            break

        results = data.get("results") or []
        if not results:
            break

        for r in results:
            company = (r.get("company") or {}).get("display_name") or "Unbekannt"
            location = (r.get("location") or {}).get("display_name") or ""
            jobs.append(Job(
                title=(r.get("title") or "").strip(),
                company=company.strip(),
                location=location,
                url=r.get("redirect_url", "") or "",
                source=NAME,
                external_id=str(r.get("id") or r.get("redirect_url") or ""),
                description=r.get("description", "") or "",
                date_posted=r.get("created", "") or "",
                lat=r.get("latitude"),
                lon=r.get("longitude"),
            ))
            if len(jobs) >= max_ergebnisse:
                break

        page += 1
        if page > 20:
            break

    return jobs


def search_all(cfg: dict) -> List[Job]:
    quelle_cfg = cfg["quellen"][NAME]
    app_id, app_key = quelle_cfg["app_id"], quelle_cfg["app_key"]
    results: List[Job] = []
    if not app_id or "DEINE" in app_id or not app_key or "DEIN_" in app_key:
        log.warning(
            "Adzuna übersprungen: app_id/app_key nicht konfiguriert. "
            "Kostenlos registrieren auf https://developer.adzuna.com/ und in "
            "config.yaml unter quellen.adzuna eintragen."
        )
        return results

    suche = cfg["suche"]
    for kw in suche["keywords"]:
        for ort in suche["orte"]:
            results.extend(search(
                kw, ort, app_id, app_key, quelle_cfg["land"],
                suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
            ))
    return results
