#!/usr/bin/env python3
"""Tkinter-Oberfläche für die Jobsuche-Automatisierung.

Vier Reiter (ttk.Notebook-Tabs):
  1. Scraper           - Suche manuell anstoßen, Live-Log
  2. Pool & Sortierung - Kennzahlen, neu bewerten ohne neue Suche
  3. Alle Stellen       - kompletter Pool (auch beworbene/limitierte)
  4. Ergebnis           - offene Treffer, absteigend nach Score sortiert
                          (bester Treffer oben), mit "Als beworben markieren"

Liest/schreibt dieselben Daten wie run_daily.py (data/jobs_pool.json), kann
also parallel zum täglichen Cron-Lauf benutzt werden.
"""
import csv
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

BASISORDNER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASISORDNER)

from jobsearch import anschreiben
from jobsearch.config import load_config
from jobsearch.dedupe import merge_pool
from jobsearch.scoring import score_job
from jobsearch.scrapers import adzuna_scraper, ba_scraper, web_scraper
from jobsearch.storage import load_pool, save_pool
from jobsearch.tracker import apply_limits, mark_applied, mark_skipped


class _QueueLogHandler(logging.Handler):
    """Leitet Python-Logging-Meldungen der Scraper (z.B. 'Adzuna übersprungen')
    zusätzlich in die Log-Anzeige der GUI um, statt sie nur im Terminal
    (sofern eins sichtbar ist) verschwinden zu lassen."""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class JobsucheApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jobsuche – Automatisierung")
        self.root.geometry("1150x680")

        self.cfg = load_config()
        self.pool_pfad = os.path.join(
            BASISORDNER, self.cfg["speicher"]["datenordner"], self.cfg["speicher"]["pool_datei"]
        )
        self.pool = load_pool(self.pool_pfad)
        self.log_queue = queue.Queue()

        log_handler = _QueueLogHandler(self.log_queue)
        log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("jobsearch").addHandler(log_handler)
        logging.getLogger("jobsearch").setLevel(logging.INFO)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.tab_scraper = ttk.Frame(notebook)
        self.tab_sortierung = ttk.Frame(notebook)
        self.tab_alle = ttk.Frame(notebook)
        self.tab_ergebnis = ttk.Frame(notebook)

        notebook.add(self.tab_scraper, text="Scraper")
        notebook.add(self.tab_sortierung, text="Pool & Sortierung")
        notebook.add(self.tab_alle, text="Alle Stellen")
        notebook.add(self.tab_ergebnis, text="Ergebnis")

        self._build_scraper_tab()
        self._build_sortierung_tab()
        self._build_alle_tab()
        self._build_ergebnis_tab()

        self._refresh_tables()
        self.root.after(200, self._poll_log_queue)

    # ---------------- Tab: Scraper ----------------
    def _build_scraper_tab(self):
        frame = self.tab_scraper
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="Bundesagentur durchsuchen",
                   command=lambda: self._run_scrape(["ba"])).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Adzuna durchsuchen",
                   command=lambda: self._run_scrape(["adzuna"])).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Web-Scraping (Stepstone/Indeed)",
                   command=lambda: self._run_scrape(["web"])).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Alle Quellen (wie täglicher Cron-Lauf)",
                   command=lambda: self._run_scrape(["ba", "adzuna", "web"])).pack(side="left", padx=5)

        self.log_widget = scrolledtext.ScrolledText(frame, height=32, state="disabled")
        self.log_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _log(self, msg: str):
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", msg + "\n")
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")
        self.root.after(200, self._poll_log_queue)

    def _run_scrape(self, quellen):
        threading.Thread(target=self._scrape_worker, args=(quellen,), daemon=True).start()

    def _scrape_worker(self, quellen):
        cfg = self.cfg
        suche = cfg["suche"]
        neue_jobs = []
        try:
            if "ba" in quellen and cfg["quellen"]["bundesagentur"]["aktiv"]:
                self._log("Bundesagentur für Arbeit wird durchsucht...")
                treffer = ba_scraper.search_all(
                    suche["keywords"], suche["orte"], suche["umkreis_km"],
                    suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
                )
                neue_jobs += treffer
                self._log(f"  -> {len(treffer)} Treffer.")

            if "adzuna" in quellen and cfg["quellen"]["adzuna"]["aktiv"]:
                self._log("Adzuna wird durchsucht...")
                treffer = adzuna_scraper.search_all(
                    suche["keywords"], suche["orte"],
                    cfg["quellen"]["adzuna"]["app_id"], cfg["quellen"]["adzuna"]["app_key"],
                    cfg["quellen"]["adzuna"]["land"], suche["max_alter_tage"], suche["ergebnisse_pro_quelle"],
                )
                neue_jobs += treffer
                self._log(f"  -> {len(treffer)} Treffer.")

            if "web" in quellen and cfg["quellen"]["web_scraping"]["aktiv"]:
                self._log("Stepstone/Indeed werden durchsucht (langsam, bitte warten)...")
                treffer = web_scraper.search_all(
                    suche["keywords"], suche["orte"],
                    cfg["quellen"]["web_scraping"]["stepstone"], cfg["quellen"]["web_scraping"]["indeed"],
                    cfg["quellen"]["web_scraping"]["request_delay_sekunden"], suche["ergebnisse_pro_quelle"],
                )
                neue_jobs += treffer
                self._log(f"  -> {len(treffer)} Treffer.")

            self._log(f"Insgesamt {len(neue_jobs)} Roh-Treffer. Dedupliziere & bewerte...")
            self.pool = merge_pool(neue_jobs, self.pool, cfg["dedupe"]["fuzzy_schwelle"])
            for job in self.pool:
                score_job(job, cfg)
            self.pool = apply_limits(self.pool, cfg, BASISORDNER)
            self.pool.sort(key=lambda j: j.score, reverse=True)
            save_pool(self.pool_pfad, self.pool)

            self._log(f"Fertig. Pool enthält jetzt {len(self.pool)} Stellen.")
            self.root.after(0, self._refresh_tables)
        except Exception as exc:  # Scraper sollen die GUI nie hart abstürzen lassen
            self._log(f"FEHLER: {exc}")

    # ---------------- Tab: Pool & Sortierung ----------------
    def _build_sortierung_tab(self):
        frame = self.tab_sortierung
        self.stats_label = ttk.Label(frame, text="", justify="left", font=("TkDefaultFont", 11))
        self.stats_label.pack(anchor="w", padx=10, pady=10)

        ttk.Button(frame, text="Neu bewerten & sortieren (ohne neue Suche)",
                   command=self._rescore_only).pack(anchor="w", padx=10, pady=5)

        ttk.Label(frame, text=(
            "Gewichtungen für die Bewertung (Score 0-1000) stehen in config.yaml\n"
            "unter 'scoring'. Änderungen dort werden bei 'Neu bewerten' sofort\n"
            "berücksichtigt, ohne dass neu gescraped werden muss.\n\n"
            "Firmenlimit und Bewerbungen-Ordner-Pfad stehen unter 'bewerbungslimits'."
        ), justify="left").pack(anchor="w", padx=10, pady=10)

    def _rescore_only(self):
        self.cfg = load_config()
        for job in self.pool:
            score_job(job, self.cfg)
        self.pool = apply_limits(self.pool, self.cfg, BASISORDNER)
        self.pool.sort(key=lambda j: j.score, reverse=True)
        save_pool(self.pool_pfad, self.pool)
        self._refresh_tables()

    # ---------------- Tab: Alle Stellen ----------------
    ALLE_SPALTEN_SCHLUESSEL = {
        "titel": lambda j: j.title.lower(),
        "firma": lambda j: j.company.lower(),
        "ort": lambda j: j.location.lower(),
        "quellen": lambda j: "+".join(j.merged_sources).lower(),
        "score": lambda j: j.score,
        "status": lambda j: j.status.lower(),
    }
    ERGEBNIS_SPALTEN_SCHLUESSEL = {
        "titel": lambda j: j.title.lower(),
        "firma": lambda j: j.company.lower(),
        "ort": lambda j: j.location.lower(),
        "score": lambda j: j.score,
        "status": lambda j: j.status.lower(),
    }

    def _build_alle_tab(self):
        frame = self.tab_alle

        anschreiben_frame = ttk.Frame(frame)
        anschreiben_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(anschreiben_frame, text="Anbieter:").pack(side="left")
        anbieter_namen = list(self.cfg["anschreiben"]["anbieter"].keys())
        self.anschreiben_anbieter_var = tk.StringVar(value=self.cfg["anschreiben"]["standard_anbieter"])
        ttk.Combobox(
            anschreiben_frame, textvariable=self.anschreiben_anbieter_var,
            values=anbieter_namen, state="readonly", width=15,
        ).pack(side="left", padx=(5, 15))
        ttk.Button(anschreiben_frame, text="KI-Anschreiben erstellen",
                   command=self._create_anschreiben).pack(side="left")

        self.tree_alle_headings = {}
        self.tree_alle_sort = {"col": None, "reverse": False}
        columns = ("titel", "firma", "ort", "quellen", "score", "status")
        self.tree_alle = ttk.Treeview(frame, columns=columns, show="headings")
        for col, text, width in [
            ("titel", "Titel", 300), ("firma", "Firma", 200), ("ort", "Ort", 140),
            ("quellen", "Quelle(n)", 120), ("score", "Score", 70), ("status", "Status", 110),
        ]:
            self.tree_alle_headings[col] = text
            self.tree_alle.heading(col, text=text, command=lambda c=col: self._sort_tree(
                self.tree_alle, self.tree_alle_sort, self.ALLE_SPALTEN_SCHLUESSEL, self.tree_alle_headings, c,
            ))
            self.tree_alle.column(col, width=width, anchor="w")
        self.tree_alle.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree_alle.bind("<Double-1>", lambda e: self._open_selected(self.tree_alle))

    # ---------------- Tab: Ergebnis ----------------
    def _build_ergebnis_tab(self):
        frame = self.tab_ergebnis
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(top, text=(
            "Beste Treffer zuerst (nach Score absteigend sortiert), "
            "ohne bereits beworbene/limitierte Firmen."
        )).pack(side="left")

        self.tree_ergebnis_headings = {}
        self.tree_ergebnis_sort = {"col": None, "reverse": False}
        columns = ("titel", "firma", "ort", "score", "status")
        self.tree_ergebnis = ttk.Treeview(frame, columns=columns, show="headings")
        for col, text, width in [
            ("titel", "Titel", 320), ("firma", "Firma", 220), ("ort", "Ort", 150),
            ("score", "Score", 70), ("status", "Status", 130),
        ]:
            self.tree_ergebnis_headings[col] = text
            self.tree_ergebnis.heading(col, text=text, command=lambda c=col: self._sort_tree(
                self.tree_ergebnis, self.tree_ergebnis_sort, self.ERGEBNIS_SPALTEN_SCHLUESSEL,
                self.tree_ergebnis_headings, c,
            ))
            self.tree_ergebnis.column(col, width=width, anchor="w")
        self.tree_ergebnis.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree_ergebnis.bind("<Double-1>", lambda e: self._open_selected(self.tree_ergebnis))

        btns = ttk.Frame(frame)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Als beworben markieren", command=self._mark_applied_selected).pack(side="left", padx=5)
        ttk.Button(btns, text="Ignorieren", command=self._mark_skipped_selected).pack(side="left", padx=5)
        ttk.Button(btns, text="Als CSV exportieren", command=self._export_csv).pack(side="left", padx=5)

    # ---------------- gemeinsame Helfer ----------------
    def _sort_tree(self, tree, sort_state, spalten_schluessel, headings, col):
        """Klick auf eine Spaltenüberschrift sortiert danach; erneuter Klick
        auf dieselbe Spalte kehrt die Richtung um (Toggle)."""
        if sort_state["col"] == col:
            sort_state["reverse"] = not sort_state["reverse"]
        else:
            sort_state["col"] = col
            sort_state["reverse"] = True

        by_id = {job.id: job for job in self.pool}
        schluessel = spalten_schluessel[col]
        zeilen = [iid for iid in tree.get_children("") if iid in by_id]
        zeilen.sort(key=lambda iid: schluessel(by_id[iid]), reverse=sort_state["reverse"])
        for index, iid in enumerate(zeilen):
            tree.move(iid, "", index)

        pfeil = " ▼" if sort_state["reverse"] else " ▲"
        for c, text in headings.items():
            tree.heading(c, text=text + (pfeil if c == col else ""))

    def _refresh_tables(self):
        self.tree_alle_sort = {"col": None, "reverse": False}
        for c, text in self.tree_alle_headings.items():
            self.tree_alle.heading(c, text=text)
        for row in self.tree_alle.get_children():
            self.tree_alle.delete(row)
        for job in self.pool:
            self.tree_alle.insert("", "end", iid=job.id, values=(
                job.title, job.company, job.location, "+".join(job.merged_sources),
                int(job.score), job.status,
            ))

        self.tree_ergebnis_sort = {"col": None, "reverse": False}
        for c, text in self.tree_ergebnis_headings.items():
            self.tree_ergebnis.heading(c, text=text)
        for row in self.tree_ergebnis.get_children():
            self.tree_ergebnis.delete(row)
        sichtbar = [j for j in self.pool if j.status not in ("applied", "capped", "skipped")]
        sichtbar.sort(key=lambda j: j.score, reverse=True)
        for job in sichtbar:
            self.tree_ergebnis.insert("", "end", iid=job.id, values=(
                job.title, job.company, job.location, int(job.score), job.status,
            ))

        gesamt = len(self.pool)
        beworben = sum(1 for j in self.pool if j.status == "applied")
        limitiert = sum(1 for j in self.pool if j.status == "capped")
        ignoriert = sum(1 for j in self.pool if j.status == "skipped")
        offen = gesamt - beworben - limitiert - ignoriert
        self.stats_label.configure(text=(
            f"Stellen im Pool: {gesamt}\n"
            f"Bereits beworben/markiert: {beworben}\n"
            f"Firma am Limit (übersprungen): {limitiert}\n"
            f"Manuell ignoriert: {ignoriert}\n"
            f"Offen zur Bewerbung: {offen}"
        ))

    def _get_selected_job(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        job_id = sel[0]
        for job in self.pool:
            if job.id == job_id:
                return job
        return None

    def _open_selected(self, tree):
        job = self._get_selected_job(tree)
        if job and job.url:
            webbrowser.open(job.url)

    def _mark_applied_selected(self):
        job = self._get_selected_job(self.tree_ergebnis)
        if not job:
            return
        mark_applied(job, BASISORDNER, self.cfg)
        save_pool(self.pool_pfad, self.pool)
        self._refresh_tables()

    def _mark_skipped_selected(self):
        job = self._get_selected_job(self.tree_ergebnis)
        if not job:
            return
        mark_skipped(job, BASISORDNER, self.cfg)
        save_pool(self.pool_pfad, self.pool)
        self._refresh_tables()

    # ---------------- KI-Anschreiben ----------------
    def _create_anschreiben(self):
        job = self._get_selected_job(self.tree_alle)
        if not job:
            messagebox.showinfo("Keine Auswahl", "Bitte zuerst eine Stelle in der Tabelle auswählen.")
            return

        anbieter_name = self.anschreiben_anbieter_var.get()
        anbieter_cfg = self.cfg["anschreiben"]["anbieter"].get(anbieter_name)
        if not anbieter_cfg:
            messagebox.showerror("Fehler", f"Unbekannter Anbieter: {anbieter_name}")
            return

        beispiel_ordner = os.path.join(BASISORDNER, self.cfg["anschreiben"]["beispiel_ordner"])
        prompt = anschreiben.build_prompt(job, beispiel_ordner)

        ausgabe_ordner = os.path.join(BASISORDNER, self.cfg["anschreiben"]["ausgabe_ordner"])
        os.makedirs(ausgabe_ordner, exist_ok=True)
        dateiname_basis = re.sub(r"[^\w\-]+", "_", f"{job.company}_{job.title}").strip("_")[:80]

        if anbieter_cfg["typ"] == "browser":
            self.root.clipboard_clear()
            self.root.clipboard_append(prompt)
            self.root.update()

            prompt_pfad = os.path.join(ausgabe_ordner, f"{dateiname_basis}_prompt.txt")
            with open(prompt_pfad, "w", encoding="utf-8") as f:
                f.write(prompt)

            webbrowser.open(anbieter_cfg["url"])
            messagebox.showinfo(
                "Prompt bereit",
                f"Prompt wurde in die Zwischenablage kopiert und {anbieter_name} im Browser "
                f"geöffnet.\nEinfach im Chat einfügen (Strg+V).\n\nGespeichert unter:\n{prompt_pfad}",
            )
        elif anbieter_cfg["typ"] == "api_openai_kompatibel":
            threading.Thread(
                target=self._anschreiben_api_worker,
                args=(job, prompt, anbieter_cfg, ausgabe_ordner, dateiname_basis, anbieter_name),
                daemon=True,
            ).start()
        else:
            messagebox.showerror("Fehler", f"Unbekannter Anbieter-Typ: {anbieter_cfg['typ']!r}")

    def _anschreiben_api_worker(self, job, prompt, anbieter_cfg, ausgabe_ordner, dateiname_basis, anbieter_name):
        self._log(f"Anschreiben wird über '{anbieter_name}' generiert...")
        try:
            text = anschreiben.generate_via_api(prompt, anbieter_cfg)
        except Exception as exc:
            self._log(f"Anschreiben-Generierung fehlgeschlagen ({anbieter_name}): {exc}")
            self.root.after(0, lambda: messagebox.showerror(
                "Fehler", f"Anschreiben-Generierung über '{anbieter_name}' fehlgeschlagen:\n{exc}",
            ))
            return

        anschreiben_pfad = os.path.join(ausgabe_ordner, f"{dateiname_basis}.txt")
        with open(anschreiben_pfad, "w", encoding="utf-8") as f:
            f.write(text)
        self._log(f"Anschreiben gespeichert: {anschreiben_pfad}")
        self.root.after(0, lambda: self._show_anschreiben_fenster(job, text, anschreiben_pfad))

    def _show_anschreiben_fenster(self, job, text, pfad):
        fenster = tk.Toplevel(self.root)
        fenster.title(f"Anschreiben – {job.company}")
        fenster.geometry("650x600")

        textbox = scrolledtext.ScrolledText(fenster, wrap="word")
        textbox.pack(fill="both", expand=True, padx=10, pady=10)
        textbox.insert("1.0", text)

        def _kopieren():
            self.root.clipboard_clear()
            self.root.clipboard_append(textbox.get("1.0", "end-1c"))
            self.root.update()

        btns = ttk.Frame(fenster)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="In Zwischenablage kopieren", command=_kopieren).pack(side="left", padx=5)
        ttk.Label(btns, text=f"Gespeichert unter: {pfad}").pack(side="left", padx=10)

    def _export_csv(self):
        sichtbar = [j for j in self.pool if j.status not in ("applied", "capped", "skipped")]
        sichtbar.sort(key=lambda j: j.score, reverse=True)
        pfad = os.path.join(BASISORDNER, self.cfg["speicher"]["datenordner"], "ergebnis_export.csv")
        with open(pfad, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Titel", "Firma", "Ort", "Score", "URL", "Quelle(n)", "Status"])
            for j in sichtbar:
                writer.writerow([j.title, j.company, j.location, int(j.score), j.url,
                                  "+".join(j.merged_sources), j.status])
        messagebox.showinfo("Export", f"Exportiert nach:\n{pfad}")


def main():
    root = tk.Tk()
    JobsucheApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
