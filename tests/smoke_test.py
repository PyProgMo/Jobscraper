#!/usr/bin/env python3
"""Schneller Selbsttest OHNE Internetzugriff: prüft, ob Dedupe, Scoring und
Bewerbungslimits fehlerfrei zusammenspielen. Testet NICHT die drei Scraper
selbst (die brauchen echte Netzwerkzugriffe) - nur die Pipeline danach.

Aufruf:  python tests/smoke_test.py
"""
import os
import sys
import tempfile

BASISORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASISORDNER)

from jobsearch.config import load_config
from jobsearch.dedupe import merge_pool
from jobsearch.fit import assess_fit
from jobsearch.historie import hinweis
from jobsearch.scoring import score_job
from jobsearch.schema import Job
from jobsearch.tracker import (
    apply_limits, mark_applied, mark_rejected, tracking_daten, unmark_applied, unmark_rejected,
)


def _job(titel, firma, beschreibung, km=5, ext="x"):
    return Job(title=titel, company=firma, location="Würzburg", url="https://example.com/" + ext,
               source="ba", external_id=ext, description=beschreibung, distance_km=km)


def pruefe_chance(cfg):
    einsteiger = _job("Berufseinsteiger Python Entwickler Messtechnik (m/w/d)", "A GmbH",
                      "Master Chemie, Physik oder vergleichbar. Python, C++, Spektroskopie.", ext="a")
    senior = _job("Senior Softwarearchitekt (m/w/d)", "B AG",
                  "Mind. 8 Jahre Berufserfahrung. Studium der Informatik. Java, C#.", ext="b")
    zu_weit = _job("Python Entwickler", "C GmbH", "Python, Linux.", km=80, ext="c")
    azubi = _job("Ausbildung Fachinformatiker", "D GmbH", "Python", ext="d")
    for j in (einsteiger, senior, zu_weit, azubi):
        assess_fit(j, cfg)
    assert einsteiger.fit > senior.fit + 30, (einsteiger.fit, senior.fit, senior.fit_notes)
    assert any("8 J. Erfahrung" in n for n in senior.fit_notes), senior.fit_notes
    assert zu_weit.fit == 0 and azubi.fit == 0, (zu_weit.fit_notes, azubi.fit_notes)
    # "Leiterplatte" darf nicht als "Leiter" (Führungsrolle) zählen
    platine = _job("Entwickler Leiterplatten (m/w/d)", "E GmbH", "Python", ext="e")
    assess_fit(platine, cfg)
    assert not any("leiter" in n for n in platine.fit_notes), platine.fit_notes


def pruefe_tracking(cfg):
    """Häkchen setzen/entfernen: Beworben, Abgelehnt (setzt Beworben), Firmenlimit."""
    cfg = {**cfg, "bewerbungslimits": {**cfg["bewerbungslimits"], "max_bewerbungen_pro_firma": 1}}
    with tempfile.TemporaryDirectory() as basis:
        a = _job("Stelle 1", "F GmbH", "x", ext="f1")
        b = _job("Völlig andere Stelle 2", "F GmbH", "y", ext="f2")
        mark_applied(a, basis, cfg)
        mark_applied(a, basis, cfg)  # doppelt klicken darf nicht doppelt zählen
        assert list(tracking_daten(basis, cfg)) == [a.id]
        apply_limits([a, b], cfg, basis)
        assert (a.status, b.status) == ("applied", "capped"), (a.status, b.status)

        mark_rejected(a, basis, cfg)
        apply_limits([a, b], cfg, basis)
        # Absage macht die Bewerbung nicht mehr "offen": Firmenlimit ist wieder frei
        assert (a.status, b.status) == ("rejected", "new"), (a.status, b.status)

        unmark_rejected(a, basis, cfg)
        assert "rejected" not in tracking_daten(basis, cfg)[a.id]
        mark_rejected(a, basis, cfg)
        unmark_applied(a, basis, cfg)  # nimmt die Absage mit
        assert tracking_daten(basis, cfg) == {}, tracking_daten(basis, cfg)


def pruefe_historie():
    with tempfile.TemporaryDirectory() as basis:
        for ordner in ("abgelehnt/Infosim", "nanoplus", "Lebenslauf"):
            os.makedirs(os.path.join(basis, ordner))
        cfg = {"bewerbungslimits": {"historie_ordner": basis, "historie_ignorieren": ["Lebenslauf"]}}
        from jobsearch.historie import lade_historie
        h = lade_historie(cfg)
        assert {e["ordner"]: e["status"] for e in h} == {"Infosim": "abgelehnt", "nanoplus": "ordner"}, h
        assert "abgelehnt" in hinweis(_job("x", "Infosim GmbH & Co. KG", ""), h)
        assert "nanoplus" in hinweis(_job("x", "nanoplus Nanosystems GmbH", ""), h)
        assert hinweis(_job("x", "Bäckerei Müller", ""), h) == ""


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

    pruefe_chance(cfg)
    pruefe_tracking(cfg)
    pruefe_historie()

    print("Smoke-Test erfolgreich:\n")
    for job in pool:
        quellen = "+".join(job.merged_sources)
        print(f"  {job.score:6.1f}  {job.title}  @ {job.company}  [{quellen}]  Status={job.status}")


if __name__ == "__main__":
    main()
