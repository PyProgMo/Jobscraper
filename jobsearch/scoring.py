"""Bewertet jede Stelle mit einem Score von 0 bis 1000 nach Passung zum Profil.

Regelbasiert über Schlüsselwörter aus config.yaml (Abschnitt 'scoring'):
Treffer im Titel zählen doppelt, Treffer nur in der Beschreibung einfach.
Die rohe Punktsumme wird mit einer sanften Sättigungskurve auf 0..max_score
gepresst (viele Treffer bringen abnehmenden Grenznutzen statt hart bei
max_score gekappt zu werden). Gewichtungen sind bewusst in der config.yaml
und nicht im Code, damit du sie ohne Programmierkenntnisse anpassen kannst.
"""
import math
import re
from typing import Dict

from .schema import Job


def _count_hits(text: str, keyword: str) -> int:
    if not text:
        return 0
    return len(re.findall(re.escape(keyword.lower()), text.lower()))


def score_job(job: Job, cfg: dict) -> float:
    scoring_cfg = cfg["scoring"]
    keywords: Dict[str, float] = scoring_cfg.get("keywords", {})
    max_score = scoring_cfg.get("max_score", 1000)

    breakdown = {}
    raw = 0.0

    for kw, weight in keywords.items():
        title_hits = _count_hits(job.title, kw)
        desc_hits = _count_hits(job.description, kw)
        contrib = title_hits * weight * 2 + desc_hits * weight
        if contrib:
            breakdown[kw] = round(contrib, 1)
            raw += contrib

    ort_text = f"{job.location} {job.description}".lower()
    for ort, bonus in scoring_cfg.get("standort_bonus", []):
        if ort.lower() in ort_text:
            breakdown[f"standort:{ort}"] = bonus
            raw += bonus

    # Sanfte Sättigung statt hartem Cutoff: viel hilft viel, aber mit
    # abnehmendem Grenznutzen, sodass ein Job nicht schon bei wenigen
    # Treffern den Maximalscore erreicht.
    normalized = max_score * (1 - math.exp(-raw / 400.0)) if raw > 0 else 0.0
    normalized = max(0.0, min(max_score, normalized))

    job.score = round(normalized, 1)
    job.score_breakdown = breakdown
    return job.score
