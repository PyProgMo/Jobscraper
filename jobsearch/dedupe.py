"""Führt neu gescrapte Jobs mit dem bestehenden Pool zusammen und erkennt
Duplikate über Quellen hinweg (gleiche Stelle bei BA, Adzuna, Stepstone ...)."""
from typing import List

from rapidfuzz import fuzz

from .schema import Job


def _normalize(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()


def merge_pool(new_jobs: List[Job], existing_jobs: List[Job], threshold: int) -> List[Job]:
    """Fügt neue Jobs in den bestehenden Pool ein und verschmilzt Duplikate
    (gleiche Firma + sehr ähnlicher Titel) statt sie doppelt aufzunehmen."""
    pool = list(existing_jobs)
    index_by_company = {}
    index_by_id = {}
    for j in pool:
        index_by_company.setdefault(_normalize(j.company), []).append(j)
        index_by_id[j.id] = j

    for nj in new_jobs:
        # Gleiche Quelle + gleiche externe ID ist immer dieselbe Stelle,
        # auch wenn Firma/Titel beim Parsen mal leicht abweichen - deshalb
        # zuerst per ID prüfen, bevor auf die unscharfe Firma/Titel-Suche
        # zurückgefallen wird. Verhindert doppelte Pool-Einträge mit
        # identischer id (die die GUI beim Anzeigen zum Absturz bringen).
        match = index_by_id.get(nj.id)

        if not match:
            norm_company = _normalize(nj.company)
            norm_title = _normalize(nj.title)
            for existing in index_by_company.get(norm_company, []):
                similarity = fuzz.token_sort_ratio(norm_title, _normalize(existing.title))
                if similarity >= threshold:
                    match = existing
                    break

        if match:
            if nj.source not in match.merged_sources:
                match.merged_sources.append(nj.source)
            if len(nj.description) > len(match.description):
                match.description = nj.description
        else:
            pool.append(nj)
            index_by_company.setdefault(norm_company, []).append(nj)
            index_by_id[nj.id] = nj

    return pool
