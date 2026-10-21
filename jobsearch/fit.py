"""Schätzt für jede Stelle, wie realistisch eine Einladung zum Gespräch ist
(0-100), und wie weit sie vom Wohnort entfernt ist.

Anders als scoring.py (Passung der *Themen* zu deinen Interessen) fragt dieses
Modul: "Erfülle ich die Anforderungen, die in der Anzeige stehen?" - also
geforderte Berufserfahrung, Promotion, Senior-Rollen, Ausbildungsberufe, nicht
vorhandene Technologien (SPS, .NET, SAP ...) gegen Pluspunkte wie
Berufseinsteiger, Naturwissenschaften oder Python/C++.

Rein regelbasiert und über config.yaml (Abschnitt 'passung') einstellbar. Das
Ergebnis ist eine Vorauswahl mit nachvollziehbarer Begründung (job.fit_notes),
keine Entscheidung: die Grenzfälle sollte man trotzdem selbst lesen.
"""
import re
from typing import List, Optional

from .geo import Geocoder, luftlinie_km, split_orte
from .schema import Job

# "5 Jahre Berufserfahrung", "mind. 3-5 Jahren Erfahrung in ...", "3+ Jahre Praxis"
_JAHRE_VOR = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:[-–]\s*\d{1,2}\s*)?jahre?n?\b[^.\n]{0,60}?(?:erfahrung|praxis)")
# "Berufserfahrung von mindestens 3 Jahren"
_JAHRE_NACH = re.compile(
    r"(?:erfahrung|praxis)[^.\n]{0,40}?(?:von|ab|mind\w*|über)\s*(\d{1,2})\s*jahre")
_MEHRJAEHRIG = re.compile(r"\b(?:mehr|lang)jährige\w*\s+(?:\w+\s+){0,2}?(?:berufs|praxis)?erfahrung")
# Satz mit Studienanforderung, der nur ein artfremdes Fach nennt
_STUDIUM_SATZ = re.compile(r"[^.\n]*(?:studium|hochschulabschluss|bachelor|master|diplom)[^.\n]*")
_ARTFREMDES_FACH = re.compile(r"informatik|elektrotechnik|mechatronik|maschinenbau|medizintechnik|ingenieur")
_PASST_ZU_CHEMIE = re.compile(
    r"naturwissenschaft|chemi|physik|mint\b|mathemat|vergleichbar|ähnlich|verwandt|o\.\s?ä\.|related|equivalent")


def _vorkommen(text: str, stichwort: str) -> bool:
    # Links immer an der Wortgrenze: "git" soll nicht "digital" treffen.
    # Rechts offen, damit Wortstämme ("naturwissenschaft", "labor") reichen;
    # ein "$" am Ende des Stichworts erzwingt das Wortende ("leiter$" trifft
    # "Leiter (m/w/d)", aber nicht "Leiterplatte").
    wort, wortende = (stichwort[:-1], True) if stichwort.endswith("$") else (stichwort, False)
    muster = r"(?<![a-zäöüß])" + re.escape(wort.lower()) + (r"(?![a-zäöüß])" if wortende else "")
    return re.search(muster, text) is not None


def entfernung_km(job: Job, cfg: dict, geocoder: Optional[Geocoder] = None) -> Optional[float]:
    """Entfernung zum Suchzentrum: Angabe der Quelle (BA) > eigene Koordinaten >
    Geocache. None, wenn der Ort nicht aufzulösen ist."""
    if job.distance_km is not None:
        return job.distance_km
    lat0, lon0 = cfg["passung"]["zentrum"]
    if job.lat is not None and job.lon is not None:
        return round(luftlinie_km(lat0, lon0, job.lat, job.lon), 1)
    if geocoder is None:
        return None
    # "Würzburg, München": zählt der nächstgelegene Standort
    km = [luftlinie_km(lat0, lon0, t[0], t[1])
          for t in (geocoder.aus_cache(n) for n in split_orte(job.location)) if t]
    return round(min(km), 1) if km else None


def _geforderte_jahre(text: str) -> int:
    jahre = [int(m) for m in _JAHRE_VOR.findall(text)] + [int(m) for m in _JAHRE_NACH.findall(text)]
    jahre = [j for j in jahre if j <= 15]  # "20 Jahre Firmengeschichte" o.ä. ignorieren
    return max(jahre, default=0)


def assess_fit(job: Job, cfg: dict, geocoder: Optional[Geocoder] = None) -> float:
    p = cfg["passung"]
    titel = job.title.lower()
    text = f"{titel}\n{job.description.lower()}"
    notes: List[str] = []

    job.distance_km = entfernung_km(job, cfg, geocoder)

    if any(_vorkommen(titel, w) for w in p.get("ausschluss_titel", [])):
        job.fit, job.fit_notes = 0.0, ["Ausbildung/Praktikum/Werkstudent - keine Festanstellung"]
        return job.fit

    punkte = float(p.get("start", 40))
    # Bonus-Wörter haben positive, Malus-Wörter negative Werte (siehe config.yaml)
    for wort, wert in {**p.get("bonus", {}), **p.get("malus", {})}.items():
        if _vorkommen(text, wort):
            # Treffer im Titel wiegen anderthalbfach (Rolle statt Randnotiz)
            wert = wert * 1.5 if _vorkommen(titel, wort) else wert
            punkte += wert
            notes.append(f"{wert:+.0f} {wort.rstrip('$')}")
    for wort, wert in p.get("titel_malus", {}).items():
        if _vorkommen(titel, wort):
            punkte += wert
            notes.append(f"{wert:+.0f} Titel: {wort.rstrip('$')}")

    eigene = p.get("erfahrung_jahre", 0)
    verlangt = _geforderte_jahre(text)
    if verlangt > eigene + 1:  # ein Jahr Toleranz: Anzeigen sind selten so strikt
        abzug = (verlangt - eigene - 1) * p.get("malus_pro_fehlendem_jahr", 12)
        punkte -= abzug
        notes.append(f"-{abzug:.0f} verlangt {verlangt} J. Erfahrung (du: {eigene})")
    elif _MEHRJAEHRIG.search(text):
        punkte -= p.get("malus_mehrjaehrig", 10)
        notes.append(f"-{p.get('malus_mehrjaehrig', 10)} 'mehrjährige Erfahrung'")

    for satz in _STUDIUM_SATZ.findall(text):
        if _ARTFREMDES_FACH.search(satz) and not _PASST_ZU_CHEMIE.search(satz):
            punkte -= p.get("malus_studienfach", 12)
            notes.append(f"-{p.get('malus_studienfach', 12)} verlangt anderes Studienfach")
            break

    max_km = p.get("max_entfernung_km", 25)
    if job.distance_km is not None and job.distance_km > max_km:
        punkte = 0.0
        notes.append(f"{job.distance_km:.0f} km entfernt (> {max_km} km)")

    job.fit = round(max(0.0, min(100.0, punkte)), 1)
    job.fit_notes = notes
    return job.fit
