"""Verwaltet, welche Stellen bereits beworben sind, und begrenzt die Anzahl
gleichzeitiger Bewerbungen pro Firma.

Zuverlässige Quelle ist data/applied.json, gepflegt über den Button
"Als beworben markieren" in der GUI. Das ist bewusst NICHT automatisch aus
dem bestehenden Bewerbungen/-Ordner abgeleitet: die Ordnernamen dort bestehen
nur aus Kürzeln (siehe Bewerbungsautomatisierung-Skill), ein Abgleich mit den
vollen Firmennamen aus den Jobportalen wäre unzuverlässig.

Optional kannst du in config.yaml unter 'bewerbungslimits.firma_kuerzel' eine
Zuordnung "Voller Firmenname: Kürzel" pflegen. Dann wird zusätzlich der
Bewerbungen/-Ordner nach passenden Kürzeln durchsucht; ein Treffer setzt den
Status nur auf den weichen Hinweis 'moeglich_beworben' (kein automatischer
Ausschluss aus der Ergebnisliste) - so gehst du keinem Match versehentlich
verloren, wenn die Zuordnung mal nicht stimmt.
"""
import json
import os
from collections import Counter
from typing import List

from .schema import Job

APPLIED_FILE = "applied.json"


def _applied_path(basisordner: str, cfg: dict) -> str:
    return os.path.join(basisordner, cfg["speicher"]["datenordner"], APPLIED_FILE)


def _load_applied(basisordner: str, cfg: dict) -> list:
    path = _applied_path(basisordner, cfg)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_applied(basisordner: str, cfg: dict, applied: list) -> None:
    path = _applied_path(basisordner, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(applied, f, ensure_ascii=False, indent=2)


def mark_applied(job: Job, basisordner: str, cfg: dict) -> None:
    applied = _load_applied(basisordner, cfg)
    applied.append({"job_id": job.id, "company": job.company, "title": job.title})
    _save_applied(basisordner, cfg, applied)
    job.status = "applied"


def mark_skipped(job: Job, basisordner: str, cfg: dict) -> None:
    # Kein Eintrag in applied.json nötig - der Status lebt direkt am Job im Pool.
    job.status = "skipped"


def _soft_scan_bewerbungen_ordner(basisordner: str, cfg: dict) -> set:
    """Best-effort: liefert die Menge der Firmen-Kürzel, für die bereits ein
    Bewerbungsordner existiert. Nur nützlich, wenn 'firma_kuerzel' gepflegt ist."""
    limits_cfg = cfg["bewerbungslimits"]
    ordner = os.path.join(basisordner, limits_cfg.get("bewerbungen_ordner", "../Bewerbungen"))
    if not os.path.isdir(ordner):
        return set()
    kuerzel_gefunden = set()
    for name in os.listdir(ordner):
        if os.path.isdir(os.path.join(ordner, name)):
            kuerzel_gefunden.add(name.split("_")[0].lower())
    return kuerzel_gefunden


def apply_limits(pool: List[Job], cfg: dict, basisordner: str) -> List[Job]:
    """Setzt für jeden Job im Pool den passenden Status:
    'applied' (manuell markiert), 'capped' (Firmenlimit erreicht),
    'moeglich_beworben' (weicher Hinweis aus dem Bewerbungen/-Ordner),
    'skipped' bleibt unverändert, sonst 'new'."""
    limits_cfg = cfg["bewerbungslimits"]
    max_pro_firma = limits_cfg.get("max_bewerbungen_pro_firma", 2)

    applied = _load_applied(basisordner, cfg)
    applied_ids = {a["job_id"] for a in applied}
    applied_company_counts = Counter(a["company"].strip().lower() for a in applied)

    firma_kuerzel = {k.lower(): v.lower() for k, v in (limits_cfg.get("firma_kuerzel") or {}).items()}
    kuerzel_mit_ordner = _soft_scan_bewerbungen_ordner(basisordner, cfg)

    for job in pool:
        if job.status == "skipped":
            continue  # manuell ignoriert bleibt ignoriert

        if job.id in applied_ids:
            job.status = "applied"
            continue

        firma_key = job.company.strip().lower()
        if applied_company_counts.get(firma_key, 0) >= max_pro_firma:
            job.status = "capped"
            continue

        kuerzel = firma_kuerzel.get(firma_key)
        if kuerzel and kuerzel in kuerzel_mit_ordner:
            job.status = "moeglich_beworben"
            continue

        job.status = "new"

    return pool
