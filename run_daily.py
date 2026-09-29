#!/usr/bin/env python3
"""Täglicher Einstiegspunkt für Cron: durchsucht alle aktiven Quellen, poolt,
dedupliziert, bewertet und speichert die Stellen. Läuft ohne GUI, gedacht für
unbeaufsichtigten Betrieb per Cron-Job. Die Tkinter-Oberfläche (gui.py) zeigt
danach dieselben gespeicherten Daten an.
"""
import logging
import os
import sys

BASISORDNER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASISORDNER)

from jobsearch.config import load_config
from jobsearch.dedupe import merge_pool
from jobsearch.scoring import score_job
from jobsearch import scrapers
from jobsearch.storage import load_pool, save_pool
from jobsearch.tracker import apply_limits


def main():
    cfg = load_config()
    speicher = cfg["speicher"]
    log_pfad = os.path.join(BASISORDNER, speicher["log_datei"])
    os.makedirs(os.path.dirname(log_pfad), exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_pfad, encoding="utf-8"), logging.StreamHandler()],
    )
    log = logging.getLogger("run_daily")
    log.info("=== Starte tägliche Jobsuche ===")

    neue_jobs = scrapers.scrape(scrapers.NAMEN, cfg, log=log.info)
    log.info("Insgesamt %d neue Roh-Treffer gefunden.", len(neue_jobs))

    pool_pfad = os.path.join(BASISORDNER, speicher["datenordner"], speicher["pool_datei"])
    bestehender_pool = load_pool(pool_pfad)
    gesamt_pool = merge_pool(neue_jobs, bestehender_pool, cfg["dedupe"]["fuzzy_schwelle"])

    for job in gesamt_pool:
        score_job(job, cfg)

    gesamt_pool = apply_limits(gesamt_pool, cfg, BASISORDNER)
    gesamt_pool.sort(key=lambda j: j.score, reverse=True)
    save_pool(pool_pfad, gesamt_pool)

    offen = sum(1 for j in gesamt_pool if j.status == "new")
    log.info("Pool enthält jetzt %d Stellen (dedupliziert), davon %d offen zur Bewerbung.",
              len(gesamt_pool), offen)
    log.info("=== Fertig ===")


if __name__ == "__main__":
    main()
