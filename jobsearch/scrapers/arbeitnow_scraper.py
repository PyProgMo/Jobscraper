"""Scraper für die öffentliche Job-Board-API von arbeitnow.com.

Komplett kostenlos, kein API-Key nötig (siehe
https://www.arbeitnow.com/blog/job-board-api). Die API liefert aber - anders
als bei BA/Adzuna - keine Server-seitige Stichwort- oder Ort-Filterung,
sondern nur einen nach Erstellungsdatum sortierten Gesamt-Feed zum
Durchblättern. Deshalb wird der Feed hier einmal pro search_all()-Aufruf
geladen (wenige Seiten, siehe MAX_SEITEN) und danach lokal nach Keyword,
Ort und Alter gefiltert - nicht pro Keyword/Ort neu abgefragt, um den
öffentlichen Dienst nicht unnötig zu belasten ("please do not abuse", siehe
API-Antwort).

Der Feed ist trotz des Namens nicht rein deutschlandweit (u.a. auch Stellen
aus UK/Frankreich dabei), das Ortsfeld ist unstrukturierter Freitext ohne
Land. Für "Ort = deutschlandweit" (orte="") wird deshalb best-effort anhand
eines Ortsnamen-Abgleichs gefiltert statt einfach alles durchzulassen.
"""
import logging
import time
from typing import List

import requests

from ..schema import Job

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_SEITEN = 5  # 5 * 250 = bis zu 1250 aktuelle Angebote pro Lauf

log = logging.getLogger(__name__)

# Best-effort-Liste großer deutscher Städte für die "deutschlandweit"-Filterung
# (orte=""), da die API kein strukturiertes Land-/Region-Feld liefert. Nicht
# abschließend, aber deckt die große Mehrheit ab.
DEUTSCHE_STAEDTE = {
    "berlin", "hamburg", "münchen", "munich", "köln", "cologne", "frankfurt",
    "stuttgart", "düsseldorf", "dusseldorf", "leipzig", "dortmund", "essen",
    "bremen", "dresden", "hannover", "nürnberg", "nuremberg", "duisburg",
    "bochum", "wuppertal", "bielefeld", "bonn", "münster", "muenster",
    "karlsruhe", "mannheim", "augsburg", "wiesbaden", "mönchengladbach",
    "gelsenkirchen", "braunschweig", "chemnitz", "kiel", "aachen", "halle",
    "magdeburg", "freiburg", "krefeld", "lübeck", "luebeck", "oberhausen",
    "erfurt", "mainz", "rostock", "kassel", "hagen", "potsdam", "saarbrücken",
    "saarbruecken", "hamm", "mülheim", "ludwigshafen", "oldenburg",
    "leverkusen", "osnabrück", "osnabrueck", "solingen", "heidelberg",
    "herne", "neuss", "darmstadt", "paderborn", "regensburg", "ingolstadt",
    "würzburg", "wuerzburg", "fürth", "wolfsburg", "offenbach", "ulm",
    "heilbronn", "pforzheim", "göttingen", "goettingen", "bottrop", "trier",
    "reutlingen", "koblenz", "erlangen", "siegen", "jena", "gerbrunn",
}
DEUTSCHLAND_MARKER = ("germany", "deutschland", "(ger)", " ger)", "d-")


def _ist_deutschland(ort_text: str) -> bool:
    text = ort_text.lower()
    if any(marker in text for marker in DEUTSCHLAND_MARKER):
        return True
    return any(stadt in text for stadt in DEUTSCHE_STAEDTE)


def _hole_feed(max_seiten: int) -> List[dict]:
    alle = []
    for seite in range(1, max_seiten + 1):
        try:
            resp = requests.get(BASE_URL, params={"page": seite}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("Arbeitnow-Abfrage fehlgeschlagen (Seite %d): %s", seite, exc)
            break
        except ValueError as exc:
            log.warning("Arbeitnow-Antwort war kein gültiges JSON (Seite %d): %s", seite, exc)
            break

        eintraege = data.get("data") or []
        if not eintraege:
            break
        alle.extend(eintraege)

        if not (data.get("links") or {}).get("next"):
            break
        time.sleep(0.3)

    return alle


def _passt_zu_keyword(eintrag: dict, keyword: str) -> bool:
    text = f"{eintrag.get('title', '')} {eintrag.get('description', '')}".lower()
    return all(wort in text for wort in keyword.lower().split())


def _passt_zu_ort(eintrag: dict, ort: str) -> bool:
    ort_text = eintrag.get("location") or ""
    ist_remote = bool(eintrag.get("remote"))

    if not ort:
        # "deutschlandweit": Remote-Stellen zulassen, sonst nur erkennbar
        # deutsche Orte (siehe Modul-Docstring - Freitext-Feld ohne Land).
        return ist_remote or _ist_deutschland(ort_text)

    if ist_remote and ort.lower() in ("remote", "homeoffice"):
        return True
    return ort.lower() in ort_text.lower()


def _unix_zu_datum(ts) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except (ValueError, OSError, TypeError):
        return ""


def _parse_eintrag(e: dict) -> Job:
    return Job(
        title=(e.get("title") or "").strip(),
        company=(e.get("company_name") or "Unbekannt").strip(),
        location=e.get("location") or ("Remote" if e.get("remote") else ""),
        url=e.get("url") or "",
        source="arbeitnow",
        external_id=e.get("slug") or e.get("url") or "",
        description=e.get("description", "") or "",
        date_posted=_unix_zu_datum(e.get("created_at")),
    )


def search_all(keywords, orte, max_alter_tage: int, max_ergebnisse: int) -> List[Job]:
    feed = _hole_feed(MAX_SEITEN)
    if not feed:
        return []

    grenze = time.time() - max_alter_tage * 86400
    aktuell = [e for e in feed if (e.get("created_at") or 0) >= grenze]

    ergebnisse: List[Job] = []
    gesehene_urls = set()
    for kw in keywords:
        for ort in orte:
            treffer = 0
            for e in aktuell:
                url = e.get("url") or ""
                if url in gesehene_urls:
                    continue
                if not _passt_zu_keyword(e, kw):
                    continue
                if not _passt_zu_ort(e, ort):
                    continue

                ergebnisse.append(_parse_eintrag(e))
                gesehene_urls.add(url)
                treffer += 1
                if treffer >= max_ergebnisse:
                    break

    return ergebnisse
