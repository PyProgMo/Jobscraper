"""Persistiert den Job-Pool als JSON-Datei."""
import json
import os
from typing import List

from .schema import Job


def load_pool(path: str) -> List[Job]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    jobs = [Job.from_dict(d) for d in raw]

    # Absicherung gegen alte/fehlerhafte Scraper-Läufe, die verschiedenen
    # Stellen dieselbe id zugewiesen haben (z.B. durch einen Link-Auswahl-Bug
    # im Stepstone-Scraper): doppelte ids crashen sonst die GUI beim Anzeigen
    # (Treeview verlangt eindeutige iids). Bei Duplikaten wird der Eintrag mit
    # der längsten Beschreibung behalten und dessen Status/Quellen ergänzt.
    by_id = {}
    for job in jobs:
        vorhanden = by_id.get(job.id)
        if vorhanden is None:
            by_id[job.id] = job
            continue
        for quelle in job.merged_sources:
            if quelle not in vorhanden.merged_sources:
                vorhanden.merged_sources.append(quelle)
        if vorhanden.status == "new" and job.status != "new":
            vorhanden.status = job.status
        if len(job.description) > len(vorhanden.description):
            vorhanden.description = job.description

    return list(by_id.values())


def save_pool(path: str, pool: List[Job]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([j.to_dict() for j in pool], f, ensure_ascii=False, indent=2)
