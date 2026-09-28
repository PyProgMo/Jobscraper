"""Ortsangaben der Stellen -> Koordinaten und Cluster für den Standorte-Reiter.

Koordinaten kommen, wo möglich, direkt von der Quelle (BA und Adzuna liefern
Breite/Länge mit). Alle anderen Ortsangaben werden über Nominatim
(OpenStreetMap) nachgeschlagen. Die Nutzungsbedingungen von Nominatim
verlangen max. 1 Anfrage pro Sekunde und einen Cache - deshalb landet jedes
Ergebnis (auch "nicht gefunden") in data/geocache.json und wird nie doppelt
angefragt. Der erste Lauf dauert bei einigen hundert Orten also ein paar
Minuten, danach ist die Karte sofort da.

Die Ortsfelder der Quellen sind uneinheitlich, z.B.:
  BA:        "Nürnberg, Mittelfranken, BAYERN"   -> nur "Nürnberg"
  Stepstone: "Berlin, München"                   -> zwei Orte
  diverse:   "bundesweit", "keine Angabe"        -> kein Ort
split_orte() macht daraus eine Liste einzelner Ortsnamen.
"""
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from .schema import Job

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim verlangt einen aussagekräftigen User-Agent (keine Default-UAs).
HEADERS = {"User-Agent": "jobsuche-gui/1.0 (https://github.com/PyProgMo/jobsuche)"}
# Nominatim erlaubt "absolut max. 1 Anfrage/Sekunde" und antwortet bei
# längeren Läufen schon knapp darüber mit 429 - daher etwas Luft lassen.
MIN_ABSTAND_SEKUNDEN = 1.5
WARTEN_BEI_429_SEKUNDEN = 60

# Angaben, die kein konkreter Ort sind und gar nicht erst angefragt werden.
KEINE_ORTE = {
    "bundesweit", "deutschlandweit", "keine angabe", "k.a.", "remote", "homeoffice",
    "home office", "home-office", "hybrid", "mobil", "deutschland", "germany", "de",
    "österreich", "austria", "schweiz", "switzerland", "europa", "europe", "dach",
    "weltweit", "worldwide", "international", "remote job",
}
# Nominatim findet auch Bundesländer/Staaten ("Bavaria") - die sind als
# Stecknadel in der Mitte des Landes irreführend und werden verworfen.
ABGELEHNTE_TYPEN = {"continent", "country", "state", "region", "political"}
# kreisfreie Städte wie Würzburg meldet Nominatim als "county"
GANZE_ORTE = {"city", "town", "village", "municipality", "county", "hamlet"}


def split_orte(location: str) -> List[str]:
    """Zerlegt ein Ortsfeld in einzelne Ortsnamen (siehe Modul-Docstring)."""
    s = re.sub(r"^\s*(bezirk|region|landkreis|kreis)\s*:\s*", "", location or "", flags=re.I)
    # Erklärende Klammern mit Aufzählung ("Visbek (zwischen Bremen und
    # Osnabrück)") entfernen, bevor an Kommas/"und" getrennt wird - sonst
    # entstehen Bruchstücke wie "Osnabrück)". "Halle (Saale)" bleibt stehen.
    s = re.sub(r"\s*\([^()]*(?:,|\s+und\s+|zwischen)[^()]*\)", "", s)
    ergebnis: List[str] = []
    # "/" nur mit Leerzeichen trennen: "Remote / Düsseldorf" sind zwei
    # Angaben, "Frankfurt/Main" oder "Kirchheim/Teck" ist ein Ort.
    for segment in re.split(r"[;|]|\s+[/-]\s+|\s+(?:und|oder|&)\s+", s):
        teile = [t.strip() for t in segment.split(",") if t.strip()]
        if not teile:
            continue
        # BA-Format "Ort[, Zusatz], REGION" (REGION in Großbuchstaben, z.B.
        # BADEN_WUERTTEMBERG oder DE): nur der erste Teil ist der Ort. Der
        # Zusatz ("Lahn", "Baden") wäre sonst ein eigener, falscher Ort.
        if len(teile) >= 2 and re.fullmatch(r"[A-ZÄÖÜ_]{2,}", teile[-1]):
            teile = teile[:1]
        for t in teile:
            t = re.sub(r"^\d{4,5}\s+", "", t)  # führende PLZ
            t = re.sub(r"\s+HQ$", "", t)       # "Berlin HQ"
            ohne_klammer = re.sub(r"\s*\(.*?\)", "", t).strip().lower()
            if not t or ohne_klammer in KEINE_ORTE or re.search(r"\bPLZ\b", t) or t in ergebnis:
                continue
            ergebnis.append(t)
    return ergebnis


class Geocoder:
    """Nominatim-Abfrage mit dauerhaftem Cache (Name -> [lat, lon, Anzeigename]
    oder None für "nicht gefunden")."""

    def __init__(self, cache_pfad: str):
        self.cache_pfad = cache_pfad
        self.cache: Dict[str, Optional[list]] = {}
        self._letzte_anfrage = 0.0
        if os.path.exists(cache_pfad):
            try:
                with open(cache_pfad, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, ValueError) as exc:
                log.warning("Geocache %s nicht lesbar, starte leer: %s", cache_pfad, exc)

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower()

    def ist_bekannt(self, name: str) -> bool:
        return self._key(name) in self.cache

    def aus_cache(self, name: str) -> Optional[list]:
        return self.cache.get(self._key(name))

    def _anfrage(self, q: str) -> Optional[list]:
        for versuch in range(2):
            warten = self._letzte_anfrage + MIN_ABSTAND_SEKUNDEN - time.monotonic()
            if warten > 0:
                time.sleep(warten)
            self._letzte_anfrage = time.monotonic()
            resp = requests.get(NOMINATIM_URL, headers=HEADERS, timeout=15, params={
                "q": q, "format": "jsonv2", "limit": 1,
                "featureType": "settlement", "accept-language": "de",
            })
            if resp.status_code == 429 and versuch == 0:
                log.info("OpenStreetMap bittet um eine Pause - warte %d s ...", WARTEN_BEI_429_SEKUNDEN)
                time.sleep(WARTEN_BEI_429_SEKUNDEN)
                continue
            break
        resp.raise_for_status()
        for treffer in resp.json():
            typ = treffer.get("addresstype")
            if typ in ABGELEHNTE_TYPEN:
                continue
            # Den Namen von Nominatim nur für ganze Orte übernehmen ("Munich"
            # -> "München", damit beide an derselben Nadel landen). Bei
            # Stadtteil-Treffern ("Mainz am Rhein" -> "Laubenheim") bleibt die
            # Schreibweise aus der Anzeige.
            name = treffer.get("name") if typ in GANZE_ORTE else None
            return [float(treffer["lat"]), float(treffer["lon"]), name or q]
        return None

    def nachschlagen(self, name: str) -> Optional[list]:
        """Fragt Nominatim an (Netzwerkfehler werden NICHT gecacht, damit der
        Ort beim nächsten Mal erneut versucht wird)."""
        treffer = self._anfrage(name)
        # "Oberkochen (bei Ulm)" findet Nominatim nicht, "Oberkochen" schon;
        # "Halle (Saale)" dagegen nur mit Klammer - daher erst mit, dann ohne.
        ohne_klammer = re.sub(r"\s*\(.*?\)", "", name).strip()
        if treffer is None and ohne_klammer and ohne_klammer != name:
            treffer = self._anfrage(ohne_klammer)
        # "Eislingen/Fils" -> "Eislingen", falls die Schreibweise mit Fluss
        # nicht gefunden wird.
        if treffer is None and "/" in ohne_klammer:
            treffer = self._anfrage(ohne_klammer.split("/")[0].strip())
        # "Gräfelfing bei München" -> "Gräfelfing". Nur als Rückfall, weil es
        # auch echte Ortsnamen mit "bei" gibt ("Feldkirchen bei Graz").
        if treffer is None and " bei " in ohne_klammer:
            treffer = self._anfrage(ohne_klammer.split(" bei ")[0].strip())
        self.cache[self._key(name)] = treffer
        return treffer

    def speichern(self) -> None:
        os.makedirs(os.path.dirname(self.cache_pfad), exist_ok=True)
        tmp = self.cache_pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.cache_pfad)


def fehlende_orte(jobs: List[Job], geocoder: Geocoder) -> List[str]:
    """Ortsnamen, die noch nachgeschlagen werden müssen (Jobs mit
    Quell-Koordinaten brauchen keinen Nominatim-Aufruf)."""
    fehlend = []
    for job in jobs:
        if job.lat is not None and job.lon is not None:
            continue
        for name in split_orte(job.location):
            if not geocoder.ist_bekannt(name) and name not in fehlend:
                fehlend.append(name)
    return fehlend


@dataclass
class Ort:
    name: str
    lat: float
    lon: float
    jobs: List[Job] = field(default_factory=list)


def orte_sammeln(jobs: List[Job], geocoder: Geocoder) -> Tuple[List[Ort], int]:
    """Gruppiert Jobs nach Ort (Name, nicht exakte Koordinate - BA liefert
    Straßen-Koordinaten, die sonst lauter Einzel-Orte in derselben Stadt
    ergäben). Ein Job mit mehreren Orten erscheint an jedem davon.
    Rückgabe: (Orte, Anzahl Jobs ohne bekannten Ort)."""
    orte: Dict[str, Ort] = {}
    summen: Dict[str, list] = {}
    ohne_ort = 0

    for job in jobs:
        positionen = []
        namen = split_orte(job.location)
        if job.lat is not None and job.lon is not None:
            positionen.append((namen[0] if namen else job.location or "?", job.lat, job.lon))
        else:
            for name in namen:
                treffer = geocoder.aus_cache(name)
                if treffer:
                    positionen.append((treffer[2], treffer[0], treffer[1]))
        if not positionen:
            ohne_ort += 1
            continue

        for name, lat, lon in positionen:
            key = name.lower()
            if key not in orte:
                orte[key] = Ort(name, lat, lon)
                summen[key] = [0.0, 0.0, 0, set()]
            s = summen[key]
            if job.id not in s[3]:
                s[3].add(job.id)
                orte[key].jobs.append(job)
                s[0] += lat
                s[1] += lon
                s[2] += 1

    for key, ort in orte.items():
        s = summen[key]
        ort.lat, ort.lon = s[0] / s[2], s[1] / s[2]
    return list(orte.values()), ohne_ort


def welt_pixel(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Web-Mercator-Pixelkoordinate (256er-Kacheln) - dieselbe Projektion wie
    die OSM-Kacheln der Karte, damit Cluster-Radien echte Bildschirm-Pixel sind."""
    lat = max(min(lat, 85.0511), -85.0511)
    n = 256 * 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def pixel_zu_grad(x: float, y: float, zoom: int) -> Tuple[float, float]:
    n = 256 * 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


@dataclass
class Cluster:
    orte: List[Ort]
    lat: float
    lon: float

    @property
    def jobs(self) -> List[Job]:
        gesehen, ergebnis = set(), []
        for ort in self.orte:
            for job in ort.jobs:
                if job.id not in gesehen:
                    gesehen.add(job.id)
                    ergebnis.append(job)
        return ergebnis

    def beschriftung(self, max_namen: int = 2) -> str:
        namen = [o.name for o in self.orte[:max_namen]]
        rest = len(self.orte) - len(namen)
        text = ", ".join(namen) + (f" +{rest}" if rest else "")
        return f"{text} ({len(self.jobs)})"


def clustern(orte: List[Ort], zoom: int, radius_px: float) -> List[Cluster]:
    """Gieriges Distanz-Clustering in Bildschirm-Pixeln beim aktuellen Zoom:
    der Ort mit den meisten Jobs wird Cluster-Mittelpunkt und schluckt alle
    Orte im Umkreis von radius_px. Der Mittelpunkt bleibt die größte Stadt,
    damit Stecknadel und Beschriftung zusammenpassen."""
    sortiert = sorted(orte, key=lambda o: len(o.jobs), reverse=True)
    cluster: List[Tuple[float, float, Cluster]] = []
    r2 = radius_px * radius_px
    for ort in sortiert:
        x, y = welt_pixel(ort.lat, ort.lon, zoom)
        for cx, cy, c in cluster:
            if (cx - x) ** 2 + (cy - y) ** 2 <= r2:
                c.orte.append(ort)
                break
        else:
            cluster.append((x, y, Cluster([ort], ort.lat, ort.lon)))
    return [c for _, _, c in cluster]


def spirale(anzahl: int, abstand_px: float) -> List[Tuple[float, float]]:
    """Pixel-Versätze (Sonnenblumen-Muster) um einen Punkt, damit mehrere
    Stellen am selben Ort als einzelne Stecknadeln nebeneinander sichtbar
    sind statt übereinander zu liegen."""
    if anzahl <= 1:
        return [(0.0, 0.0)]
    goldener_winkel = math.pi * (3 - math.sqrt(5))
    return [
        (abstand_px * math.sqrt(i + 0.5) * math.cos(i * goldener_winkel),
         abstand_px * math.sqrt(i + 0.5) * math.sin(i * goldener_winkel))
        for i in range(anzahl)
    ]
