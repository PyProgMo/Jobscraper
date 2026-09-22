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
from jobsearch.scrapers import adzuna_scraper, arbeitnow_scraper, ba_scraper, web_scraper
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

    suche = cfg["suche"]
    quellen = cfg["quellen"]
    neue_jobs = []

    if quellen["bundesagentur"]["aktiv"]:
        log.info("Suche bei der Bundesagentur für Arbeit...")
        neue_jobs += ba_scraper.search_all(
            suche["keywords"], suche["orte"], suche["umkreis_km"],
            suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
        )

    if quellen["arbeitnow"]["aktiv"]:
        log.info("Suche bei Arbeitnow...")
        neue_jobs += arbeitnow_scraper.search_all(
            suche["keywords"], suche["orte"],
            suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
        )

    if quellen["adzuna"]["aktiv"]:
        log.info("Suche bei Adzuna...")
        neue_jobs += adzuna_scraper.search_all(
            suche["keywords"], suche["orte"],
            quellen["adzuna"]["app_id"], quellen["adzuna"]["app_key"], quellen["adzuna"]["land"],
            suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
        )

    if quellen["web_scraping"]["aktiv"]:
        log.info("Suche per Web-Scraping (Stepstone/Indeed)...")
        neue_jobs += web_scraper.search_all(
            suche["keywords"], suche["orte"],
            quellen["web_scraping"]["stepstone"], quellen["web_scraping"]["indeed"],
            quellen["web_scraping"]["request_delay_sekunden"], suche["ergebnisse_pro_quelle"],
        )

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
