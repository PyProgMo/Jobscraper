"""Auswahl und Reihenfolge der Stellen im Reiter "Empfehlungen".

Zwei Quellen, in dieser Rangfolge:
  1. Handbewertung in data/empfehlungen.json (Anzeige gelesen und gegen den
     Lebenslauf geprüft): "top" | "gut" | "moeglich" | "nein" (= ausblenden),
     mit eigener Chance 0-100, Begründung und Risiken.
  2. Automatik: alle übrigen Stellen im Umkreis, deren 'fit' (jobsearch/fit.py)
     und Themen-Score über den Schwellen aus config.yaml ('empfehlung') liegen.
     So tauchen auch neue Treffer des täglichen Cron-Laufs auf, ohne dass
     jemand sie vorher von Hand bewertet hat.

Format von empfehlungen.json - eine Liste von Objekten:
  {"job_id": "...", "einschaetzung": "top", "chance": 78,
   "begruendung": "...", "risiken": "...", "titel": "...", "firma": "..."}
(titel/firma sind nur zur Lesbarkeit der Datei da; maßgeblich ist job_id.)
"""
import json
import os
from typing import Dict, List

from .schema import Job

DATEI = "empfehlungen.json"
STUFEN = {"top": ("Top", 0), "gut": ("Gut", 1), "moeglich": ("Möglich", 2)}
AUTO = ("auto", 3)


def lade_kuratiert(basisordner: str, cfg: dict) -> Dict[str, dict]:
    pfad = os.path.join(basisordner, cfg["speicher"]["datenordner"], DATEI)
    if not os.path.exists(pfad):
        return {}
    with open(pfad, "r", encoding="utf-8") as f:
        return {e["job_id"]: e for e in json.load(f)}


def stufe(job: Job, kuratiert: Dict[str, dict]) -> tuple:
    """(Anzeigename, Rang) - Rang 0 = beste Stufe."""
    k = kuratiert.get(job.id)
    return STUFEN.get(k["einschaetzung"], AUTO) if k else AUTO


def chance(job: Job, kuratiert: Dict[str, dict]) -> float:
    k = kuratiert.get(job.id)
    return float(k["chance"]) if k and "chance" in k else job.fit


def auswahl(pool: List[Job], cfg: dict, kuratiert: Dict[str, dict], tracking: dict) -> List[Job]:
    """Empfohlene Stellen, beste zuerst. Bereits beworbene/abgelehnte bleiben
    drin (sonst könnte man sie nicht mehr abhaken); ignorierte nur, wenn sie
    ein Häkchen haben."""
    max_km = cfg["passung"]["max_entfernung_km"]
    schwellen = cfg["empfehlung"]
    ergebnis = []
    for j in pool:
        k = kuratiert.get(j.id)
        if k and k["einschaetzung"] == "nein":
            continue
        if j.status == "skipped" and j.id not in tracking:
            continue
        if k and k["einschaetzung"] in STUFEN:
            ergebnis.append(j)  # Handbewertung gilt auch bei unbekannter Entfernung
        elif (j.distance_km is not None and j.distance_km <= max_km
              and j.fit >= schwellen["min_fit"] and j.score >= schwellen["min_score"]):
            ergebnis.append(j)
    ergebnis.sort(key=lambda j: (stufe(j, kuratiert)[1], -chance(j, kuratiert), -j.score))
    return ergebnis
