#!/usr/bin/env python3
"""Tkinter-Oberfläche für die Jobsuche-Automatisierung.

Fünf Reiter (ttk.Notebook-Tabs):
  1. Scraper           - Suche manuell anstoßen, Live-Log
  2. Pool & Sortierung - Kennzahlen, neu bewerten ohne neue Suche
  3. Alle Stellen       - kompletter Pool (auch beworbene/limitierte)
  4. Ergebnis           - offene Treffer, absteigend nach Score sortiert
                          (bester Treffer oben), mit "Als beworben markieren"
  5. Standorte          - Weltkarte mit den Stellen als Stecknadeln (Farbe =
                          Score), beim Zoomen neu geclustert

Liest/schreibt dieselben Daten wie run_daily.py (data/jobs_pool.json), kann
also parallel zum täglichen Cron-Lauf benutzt werden.
"""
import csv
import logging
import math
import os
import queue
import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

try:
    import tkintermapview
except ImportError:  # Karte ist optional - der Rest der GUI soll trotzdem laufen
    tkintermapview = None

BASISORDNER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASISORDNER)

from jobsearch import anschreiben, geo, scrapers
from jobsearch.config import load_config
from jobsearch.dedupe import merge_pool
from jobsearch.scoring import score_job
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
        self.geocoder = geo.Geocoder(os.path.join(
            BASISORDNER, self.cfg["speicher"]["datenordner"], "geocache.json"
        ))
        self.log_queue = queue.Queue()

        log_handler = _QueueLogHandler(self.log_queue)
        log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("jobsearch").addHandler(log_handler)
        logging.getLogger("jobsearch").setLevel(logging.INFO)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        self.notebook = notebook

        self.tab_scraper = ttk.Frame(notebook)
        self.tab_sortierung = ttk.Frame(notebook)
        self.tab_alle = ttk.Frame(notebook)
        self.tab_ergebnis = ttk.Frame(notebook)
        self.tab_standorte = ttk.Frame(notebook)

        notebook.add(self.tab_scraper, text="Scraper")
        notebook.add(self.tab_sortierung, text="Pool & Sortierung")
        notebook.add(self.tab_alle, text="Alle Stellen")
        notebook.add(self.tab_ergebnis, text="Ergebnis")
        notebook.add(self.tab_standorte, text="Standorte")

        self._build_scraper_tab()
        self._build_sortierung_tab()
        self._build_alle_tab()
        self._build_ergebnis_tab()
        self._build_standorte_tab()

        self._refresh_tables()
        self.root.after(200, self._poll_log_queue)

    # ---------------- Tab: Scraper ----------------
    def _build_scraper_tab(self):
        frame = self.tab_scraper
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", padx=10, pady=10)

        # Ein Button pro registriertem Quellen-Scraper (siehe
        # jobsearch/scrapers/__init__.py) - neue Quellen tauchen hier
        # automatisch auf, ohne gui.py anzufassen.
        for modul in scrapers.ALLE:
            ttk.Button(btn_frame, text=f"{modul.ANZEIGENAME} durchsuchen",
                       command=lambda n=modul.NAME: self._run_scrape([n])).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Alle Quellen (wie täglicher Cron-Lauf)",
                   command=lambda: self._run_scrape(scrapers.NAMEN)).pack(side="left", padx=5)

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
        try:
            neue_jobs = scrapers.scrape(quellen, cfg, log=self._log)

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

    # ---------------- Tab: Standorte ----------------
    # Orte, die auf dem Bildschirm näher als das beieinander liegen, werden zu
    # einer Stecknadel zusammengefasst (bei jedem Zoomschritt neu berechnet).
    KARTE_CLUSTER_RADIUS_PX = 70
    # Ab diesem Zoom (ungefähr Stadtebene) wird nicht mehr geclustert: jede
    # Stelle bekommt eine eigene Stecknadel, spiralförmig um ihren Ort verteilt.
    KARTE_EINZEL_ZOOM = 11
    KARTE_SPIRALE_ABSTAND_PX = 20

    def _build_standorte_tab(self):
        frame = self.tab_standorte
        self.karte = None
        if tkintermapview is None:
            ttk.Label(frame, text=(
                "Für die Karte fehlt das Paket 'tkintermapview'. Installieren mit:\n\n"
                "    pip install tkintermapview\n\n"
                "und die GUI neu starten."
            ), justify="left").pack(anchor="w", padx=10, pady=10)
            return

        leiste = ttk.Frame(frame)
        leiste.pack(fill="x", padx=10, pady=(10, 0))

        self.karte_score_min = tk.DoubleVar(value=0)
        self.karte_score_max = tk.DoubleVar(value=1000)
        self.karte_score_obergrenze = 1000.0
        ttk.Label(leiste, text="Score von").pack(side="left")
        self.karte_min_scale = ttk.Scale(
            leiste, from_=0, to=1000, length=150, variable=self.karte_score_min,
            command=lambda _: self._karte_regler_geaendert("min"),
        )
        self.karte_min_scale.pack(side="left", padx=(5, 0))
        self.karte_min_label = ttk.Label(leiste, width=5, anchor="e")
        self.karte_min_label.pack(side="left")
        ttk.Label(leiste, text="bis").pack(side="left", padx=(10, 0))
        self.karte_max_scale = ttk.Scale(
            leiste, from_=0, to=1000, length=150, variable=self.karte_score_max,
            command=lambda _: self._karte_regler_geaendert("max"),
        )
        self.karte_max_scale.pack(side="left", padx=(5, 0))
        self.karte_max_label = ttk.Label(leiste, width=5, anchor="e")
        self.karte_max_label.pack(side="left")

        self.karte_nur_offen = tk.BooleanVar(value=True)
        ttk.Checkbutton(leiste, text="Nur offene Stellen", variable=self.karte_nur_offen,
                        command=self._karte_zeichnen_bald).pack(side="left", padx=(15, 0))

        # Farblegende: rot = niedriger Score, grün = hoher Score
        ttk.Label(leiste, text="Farbe:").pack(side="left", padx=(15, 3))
        self.karte_legende = tk.Canvas(leiste, width=150, height=16, highlightthickness=0)
        self.karte_legende.pack(side="left")

        self.karte_status = ttk.Label(frame, text="", foreground="#555")
        self.karte_status.pack(fill="x", padx=10, pady=(5, 0))

        paned = ttk.PanedWindow(frame, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        karten_frame = ttk.Frame(paned)
        self.karte = tkintermapview.TkinterMapView(karten_frame, corner_radius=0)
        self.karte.pack(fill="both", expand=True)
        self.karte.set_position(51.1, 10.4)  # Deutschland, bis die Stellen eingepasst sind
        self.karte.set_zoom(6)
        paned.add(karten_frame, weight=3)

        liste_frame = ttk.Frame(paned)
        self.karte_auswahl_label = ttk.Label(
            liste_frame, text="Stecknadel anklicken, um die Stellen dort zu sehen.\n"
                              "Doppelklick auf eine Stelle öffnet die Anzeige.",
            justify="left", wraplength=360,
        )
        self.karte_auswahl_label.pack(anchor="w", pady=(0, 5))
        self.tree_karte = ttk.Treeview(liste_frame, columns=("score", "titel", "firma", "ort"), show="headings")
        for col, text, width in [("score", "Score", 50), ("titel", "Titel", 200),
                                 ("firma", "Firma", 130), ("ort", "Ort", 100)]:
            self.tree_karte.heading(col, text=text)
            self.tree_karte.column(col, width=width, anchor="w")
        self.tree_karte.pack(fill="both", expand=True)
        self.tree_karte.bind("<Double-1>", lambda e: self._open_selected(self.tree_karte))

        karte_btns = ttk.Frame(liste_frame)
        karte_btns.pack(fill="x", pady=(5, 0))
        ttk.Button(karte_btns, text="Webseite öffnen",
                   command=lambda: self._open_selected(self.tree_karte)).pack(side="left", padx=(0, 5))
        ttk.Button(karte_btns, text="KI-Anschreiben erstellen",
                   command=lambda: self._create_anschreiben(self.tree_karte)).pack(side="left")

        paned.add(liste_frame, weight=1)

        # 1x1-Bild als "unsichtbare" Stecknadel für reine Ortsbeschriftungen
        self._karte_leeres_icon = tk.PhotoImage(width=1, height=1)
        self._karte_zoom = None
        self._karte_ansicht = None
        self._karte_orte = []            # Orte des letzten Zeichnens (gefiltert)
        self._karte_auswahl_orte = set()  # per Klick ausgewählte Orte (Kleinschreibung)
        self._karte_zeichnen_job = None
        self._karte_eingepasst = False
        self._geocoding_laeuft = False
        self._geocoding_erneut = False
        self._geocoding_fortschritt = None

        self.notebook.bind("<<NotebookTabChanged>>", self._karte_tab_gewechselt, add="+")
        self.root.after(250, self._karte_ansicht_pruefen)

    @staticmethod
    def _score_farbe(anteil: float, aufhellen: float = 0.0, abdunkeln: float = 0.0) -> str:
        """0 = rot, 0.5 = gelb, 1 = grün (optional aufgehellt/abgedunkelt)."""
        stufen = [(0.0, (215, 48, 39)), (0.5, (250, 204, 60)), (1.0, (26, 152, 80))]
        anteil = min(max(anteil, 0.0), 1.0)
        for (a0, f0), (a1, f1) in zip(stufen, stufen[1:]):
            if anteil <= a1:
                t = (anteil - a0) / (a1 - a0)
                rgb = [c0 + (c1 - c0) * t for c0, c1 in zip(f0, f1)]
                break
        rgb = [c + (255 - c) * aufhellen for c in rgb]
        rgb = [c * (1 - abdunkeln) for c in rgb]
        return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb)

    def _karte_farben(self, score: float):
        """(Kreis, Rand) der Stecknadel. Skaliert auf den besten Score im
        Pool, damit die Farben den tatsächlich vorkommenden Bereich nutzen."""
        anteil = score / self.karte_score_obergrenze
        return self._score_farbe(anteil, abdunkeln=0.3), self._score_farbe(anteil)

    def _karte_aktualisieren(self):
        """Nach Suche/Neubewertung: Regler an den Score-Bereich anpassen,
        fehlende Orte nachschlagen und neu zeichnen."""
        if self.karte is None:
            return
        alte_grenze = self.karte_score_obergrenze
        neue_grenze = float(max(1, math.ceil(max((j.score for j in self.pool), default=1))))
        self.karte_score_obergrenze = neue_grenze
        self.karte_min_scale.configure(to=neue_grenze)
        self.karte_max_scale.configure(to=neue_grenze)
        # Stand der Max-Regler ganz rechts, bleibt er es auch bei neuer Grenze
        if self.karte_score_max.get() >= alte_grenze or self.karte_score_max.get() > neue_grenze:
            self.karte_score_max.set(neue_grenze)
        if self.karte_score_min.get() > neue_grenze:
            self.karte_score_min.set(0)
        self._karte_legende_zeichnen()
        self._karte_regler_labels()
        self._geocoding_starten()
        self._karte_zeichnen_bald()

    def _karte_legende_zeichnen(self):
        c = self.karte_legende
        c.delete("all")
        breite = int(c.cget("width"))
        for x in range(breite):
            farbe = self._score_farbe(x / (breite - 1))
            c.create_line(x, 0, x, 16, fill=farbe)
        c.create_text(3, 8, text="0", anchor="w", font=("TkDefaultFont", 8, "bold"))
        c.create_text(breite - 3, 8, text=str(int(self.karte_score_obergrenze)), anchor="e",
                      font=("TkDefaultFont", 8, "bold"), fill="white")

    def _karte_regler_labels(self):
        self.karte_min_label.configure(text=str(int(self.karte_score_min.get())))
        self.karte_max_label.configure(text=str(int(self.karte_score_max.get())))

    def _karte_regler_geaendert(self, welcher: str):
        # Die beiden Regler dürfen sich nicht überholen: wer den anderen
        # überschreitet, schiebt ihn mit.
        lo, hi = self.karte_score_min.get(), self.karte_score_max.get()
        if lo > hi:
            if welcher == "min":
                self.karte_score_max.set(lo)
            else:
                self.karte_score_min.set(hi)
        self._karte_regler_labels()
        self._karte_zeichnen_bald()

    def _karte_gefilterte_jobs(self):
        lo, hi = self.karte_score_min.get(), self.karte_score_max.get()
        nur_offen = self.karte_nur_offen.get()
        return [
            j for j in self.pool
            if lo <= j.score <= hi + 0.5  # +0.5: Regler zeigt gerundete Werte
            and not (nur_offen and j.status in ("applied", "capped", "skipped"))
        ]

    def _karte_zeichnen_bald(self):
        """Zeichnet mit kurzer Verzögerung neu, damit Regler-Ziehen nicht bei
        jedem Pixel die ganze Karte neu aufbaut."""
        if self.karte is None:
            return
        if self._karte_zeichnen_job is not None:
            self.root.after_cancel(self._karte_zeichnen_job)
        self._karte_zeichnen_job = self.root.after(150, self._karte_zeichnen)

    def _karte_ansicht_pruefen(self):
        """tkintermapview meldet Zoom/Verschieben nicht per Event - daher alle
        250 ms nachsehen. Neu gezeichnet wird bei jedem Zoomschritt, und im
        Einzel-Modus zusätzlich nach größerem Verschieben (dort werden nur die
        Stecknadeln im sichtbaren Ausschnitt erzeugt)."""
        zoom = round(self.karte.zoom)
        if zoom != self._karte_zoom:
            self._karte_zeichnen()
        elif zoom >= self.KARTE_EINZEL_ZOOM and self._karte_ansicht is not None:
            x0, y0 = self.karte.upper_left_tile_pos
            ax, ay = self._karte_ansicht
            breite_kacheln = self.karte.width / 256
            if abs(x0 - ax) > breite_kacheln / 3 or abs(y0 - ay) > breite_kacheln / 3:
                self._karte_zeichnen()
        self.root.after(250, self._karte_ansicht_pruefen)

    def _karte_marker_entfernen(self):
        # delete_all_marker() ruft pro Stecknadel canvas.update() auf - bei
        # hunderten Nadeln spürbar träge. Daher die Canvas-Objekte direkt löschen.
        canvas = self.karte.canvas
        for m in self.karte.canvas_marker_list:
            m.deleted = True
            for item in (m.polygon, m.big_circle, m.canvas_text, m.canvas_icon, m.canvas_image):
                if item is not None:
                    canvas.delete(item)
        self.karte.canvas_marker_list = []

    def _karte_zeichnen(self):
        self._karte_zeichnen_job = None
        jobs = self._karte_gefilterte_jobs()
        orte, ohne_ort = geo.orte_sammeln(jobs, self.geocoder)
        self._karte_orte = orte
        zoom = round(self.karte.zoom)
        self._karte_zoom = zoom
        self._karte_ansicht = self.karte.upper_left_tile_pos

        self._karte_marker_entfernen()
        if zoom >= self.KARTE_EINZEL_ZOOM:
            self._karte_einzeln_zeichnen(orte, zoom)
        else:
            for cluster in geo.clustern(orte, zoom, self.KARTE_CLUSTER_RADIUS_PX):
                beste = max(j.score for j in cluster.jobs)
                innen, aussen = self._karte_farben(beste)
                self.karte.set_marker(
                    cluster.lat, cluster.lon, text=cluster.beschriftung(),
                    marker_color_circle=innen, marker_color_outside=aussen,
                    text_color="#1f1f1f", font=("TkDefaultFont", 9, "bold"),
                    command=self._karte_marker_klick, data=cluster,
                )
        # Beschriftungen über alle Stecknadeln legen, damit keine Nadel eines
        # Nachbarorts einen Ortsnamen verdeckt.
        self.karte.canvas.tag_raise("marker_text")
        self._karte_liste_aktualisieren()

        auf_karte = len(jobs) - ohne_ort
        status = f"{auf_karte} von {len(jobs)} Stellen auf der Karte"
        if self._geocoding_fortschritt:
            erledigt, gesamt = self._geocoding_fortschritt
            status += (f" · Orte werden über OpenStreetMap ermittelt: {erledigt}/{gesamt} "
                       f"(einmalig, die Karte füllt sich nach und nach)")
        elif ohne_ort:
            status += f" · {ohne_ort} ohne verwertbare Ortsangabe (z.B. 'bundesweit')"
        status += " · Nadelfarbe = Score (bei Gruppen: bester Score darin)"
        self.karte_status.configure(text=status)

    def _karte_einzeln_zeichnen(self, orte, zoom):
        """Jede Stelle als eigene Nadel, spiralförmig um ihren Ort. Nur Orte im
        sichtbaren Ausschnitt (plus Rand) - sonst wären es hunderte Nadeln, und
        tkintermapview sortiert bei jedem Verschieben alle neu."""
        x0, y0 = self.karte.upper_left_tile_pos
        x1, y1 = self.karte.lower_right_tile_pos
        rand = (x1 - x0) * 0.5
        sicht = ((x0 - rand) * 256, (y0 - rand) * 256, (x1 + rand) * 256, (y1 + rand) * 256)

        beschriftungen = []
        for ort in orte:
            cx, cy = geo.welt_pixel(ort.lat, ort.lon, zoom)
            if not (sicht[0] <= cx <= sicht[2] and sicht[1] <= cy <= sicht[3]):
                continue
            jobs = sorted(ort.jobs, key=lambda j: j.score, reverse=True)
            versaetze = geo.spirale(len(jobs), self.KARTE_SPIRALE_ABSTAND_PX)
            for job, (dx, dy) in zip(jobs, versaetze):
                lat, lon = geo.pixel_zu_grad(cx + dx, cy + dy, zoom)
                innen, aussen = self._karte_farben(job.score)
                self.karte.set_marker(
                    lat, lon, marker_color_circle=innen, marker_color_outside=aussen,
                    command=self._karte_marker_klick, data=(ort, job),
                )
            radius = max(math.hypot(dx, dy) for dx, dy in versaetze)
            beschriftungen.append((ort, radius))

        # Ortsname unter die Spirale (Nadelspitzen zeigen auf den Ort, die
        # Köpfe ragen nach oben - unten ist also Platz).
        for ort, radius in beschriftungen:
            label = self.karte.set_marker(
                ort.lat, ort.lon, text=f"{ort.name} ({len(ort.jobs)})",
                icon=self._karte_leeres_icon, text_color="#1f1f1f",
                font=("TkDefaultFont", 9, "bold"),
            )
            label.text_y_offset = radius + 20
            label.draw()

    def _karte_marker_klick(self, marker):
        # Gemerkt werden die angeklickten Orte, nicht die Jobs: so kann die
        # Liste bei jeder Filteränderung (Score-Regler, "Nur offene") neu
        # aus denselben Orten befüllt werden.
        daten = marker.data
        if isinstance(daten, geo.Cluster):
            self._karte_auswahl_orte = {o.name.lower() for o in daten.orte}
            self._karte_liste_aktualisieren()
            if len(daten.orte) > 1:
                # wie bei Web-Karten üblich: Klick auf ein Cluster zoomt hinein
                self.karte.set_position(daten.lat, daten.lon)
                self.karte.set_zoom(round(self.karte.zoom) + 2)
        else:
            ort, job = daten
            self._karte_auswahl_orte = {ort.name.lower()}
            self._karte_liste_aktualisieren(auswahl_id=job.id)

    def _karte_liste_aktualisieren(self, auswahl_id=None):
        """Füllt die Liste rechts mit den Stellen der ausgewählten Orte, die
        den aktuellen Filter erfüllen. Wird nach jedem Neuzeichnen aufgerufen."""
        if not self._karte_auswahl_orte:
            return
        tree = self.tree_karte
        if auswahl_id is None and tree.selection():
            auswahl_id = tree.selection()[0]  # Markierung über Filteränderungen retten

        orte = sorted((o for o in self._karte_orte if o.name.lower() in self._karte_auswahl_orte),
                      key=lambda o: len(o.jobs), reverse=True)
        if orte:
            cluster = geo.Cluster(orte, orte[0].lat, orte[0].lon)
            ueberschrift, jobs = cluster.beschriftung(max_namen=6), cluster.jobs
        else:
            ueberschrift, jobs = "Keine Stellen dieser Auswahl im eingestellten Score-Bereich.", []
        self.karte_auswahl_label.configure(text=ueberschrift)

        tree.delete(*tree.get_children())
        for job in sorted(jobs, key=lambda j: j.score, reverse=True):
            farbe = self._score_farbe(job.score / self.karte_score_obergrenze, aufhellen=0.6)
            tree.tag_configure(farbe, background=farbe)
            tree.insert("", "end", iid=job.id, tags=(farbe,), values=(
                int(job.score), job.title, job.company, job.location,
            ))
        if auswahl_id is not None and tree.exists(auswahl_id):
            tree.selection_set(auswahl_id)
            tree.see(auswahl_id)

    def _karte_tab_gewechselt(self, _event=None):
        if self.karte is None or self._karte_eingepasst:
            return
        if self.notebook.select() == str(self.tab_standorte):
            # erst nach dem Einblenden hat die Karte ihre echte Größe
            self.root.after(100, self._karte_einpassen)

    def _karte_einpassen(self):
        """Beim ersten Öffnen des Reiters auf alle Stellen zoomen."""
        orte, _ = geo.orte_sammeln(self._karte_gefilterte_jobs(), self.geocoder)
        if not orte:
            return  # noch nichts geocodiert - Deutschland-Ansicht bleibt
        self._karte_eingepasst = True
        lats = [o.lat for o in orte]
        lons = [o.lon for o in orte]
        if max(lats) - min(lats) < 0.05 and max(lons) - min(lons) < 0.05:
            self.karte.set_position(lats[0], lons[0])
            self.karte.set_zoom(10)
        else:
            self.karte.fit_bounding_box((max(lats), min(lons)), (min(lats), max(lons)))
        self._karte_zeichnen()

    def _geocoding_starten(self):
        if self._geocoding_laeuft:
            self._geocoding_erneut = True  # nach dem aktuellen Lauf nochmal prüfen
            return
        fehlend = geo.fehlende_orte(self.pool, self.geocoder)
        if not fehlend:
            return
        self._geocoding_laeuft = True
        self._geocoding_fortschritt = (0, len(fehlend))
        threading.Thread(target=self._geocoding_worker, args=(fehlend,), daemon=True).start()

    def _geocoding_worker(self, fehlend):
        fehler_in_folge = 0
        try:
            for i, name in enumerate(fehlend, 1):
                try:
                    self.geocoder.nachschlagen(name)
                    fehler_in_folge = 0
                except Exception as exc:
                    fehler_in_folge += 1
                    self._log(f"Ort {name!r} konnte nicht nachgeschlagen werden: {exc}")
                    if fehler_in_folge >= 3:
                        self._log("Ortssuche abgebrochen (offline oder OpenStreetMap nicht erreichbar). "
                                  "Wird beim nächsten Start erneut versucht.")
                        break
                self._geocoding_fortschritt = (i, len(fehlend))
                if i % 10 == 0:
                    self.geocoder.speichern()
                    self.root.after(0, self._karte_zeichnen_bald)
        finally:
            self.geocoder.speichern()
            self.root.after(0, self._geocoding_fertig)

    def _geocoding_fertig(self):
        self._geocoding_laeuft = False
        self._geocoding_fortschritt = None
        if self._geocoding_erneut:
            self._geocoding_erneut = False
            self._geocoding_starten()
        if not self._karte_eingepasst and self.notebook.select() == str(self.tab_standorte):
            self._karte_einpassen()
        self._karte_zeichnen_bald()

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
        self._karte_aktualisieren()

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
    def _create_anschreiben(self, tree=None):
        job = self._get_selected_job(tree or self.tree_alle)
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
            # Python löscht die "as exc"-Variable automatisch am Ende des
            # except-Blocks - bis die per root.after() verzögerte Lambda
            # tatsächlich läuft, wäre "exc" sonst schon wieder ungebunden.
            # Deshalb die Meldung sofort in einen normalen String umwandeln.
            fehlermeldung = str(exc)
            self._log(f"Anschreiben-Generierung fehlgeschlagen ({anbieter_name}): {fehlermeldung}")
            self.root.after(0, lambda: messagebox.showerror(
                "Fehler", f"Anschreiben-Generierung über '{anbieter_name}' fehlgeschlagen:\n{fehlermeldung}",
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
