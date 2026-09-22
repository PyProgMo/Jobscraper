#!/usr/bin/env python3
"""Schneller Selbsttest OHNE Internetzugriff: prüft, ob Dedupe, Scoring und
Bewerbungslimits fehlerfrei zusammenspielen. Testet NICHT die drei Scraper
selbst (die brauchen echte Netzwerkzugriffe) - nur die Pipeline danach.

Aufruf:  python tests/smoke_test.py
"""
import os
import sys

BASISORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASISORDNER)

from jobsearch.config import load_config
from jobsearch.dedupe import merge_pool
from jobsearch.scoring import score_job
from jobsearch.schema import Job
from jobsearch.tracker import apply_limits


def main():
    cfg = load_config()

    j1 = Job(title="Python Softwareentwickler (m/w/d)", company="Beispiel GmbH",
             location="Würzburg", url="https://example.com/1", source="ba", external_id="1",
             description="Wir suchen einen Python- und C++-Entwickler für Automatisierung im Labor.")
    j2 = Job(title="Python Software-Entwickler m/w/d", company="Beispiel GmbH",
             location="Würzburg", url="https://example.com/2", source="adzuna", external_id="2",
             description="Python C++ Automatisierung, Data Science von Vorteil.")
    j3 = Job(title="Bäcker (m/w/d)", company="Bäckerei Müller",
             location="Berlin", url="https://example.com/3", source="stepstone", external_id="3",
             description="Backwaren herstellen, frühes Aufstehen.")

    pool = merge_pool([j1, j2, j3], [], cfg["dedupe"]["fuzzy_schwelle"])
    assert len(pool) == 2, f"Erwartet 2 Stellen nach Dedupe (j1+j2 sollten verschmelzen), bekommen {len(pool)}"

    for job in pool:
        score_job(job, cfg)

    pool.sort(key=lambda j: j.score, reverse=True)
    assert pool[0].company == "Beispiel GmbH", "Der Software-Job sollte höher scoren als der Bäcker-Job"
    assert pool[0].score > pool[1].score, "Score-Reihenfolge stimmt nicht"

    pool = apply_limits(pool, cfg, BASISORDNER)

    print("Smoke-Test erfolgreich:\n")
    for job in pool:
        quellen = "+".join(job.merged_sources)
        print(f"  {job.score:6.1f}  {job.title}  @ {job.company}  [{quellen}]  Status={job.status}")


if __name__ == "__main__":
    main()
