"""Erkennt Firmen, bei denen du dich schon beworben hast oder abgelehnt wurdest,
anhand deiner Bewerbungsordner.

Gelesen werden nur die *Ordnernamen* (nie Dateiinhalte):
  <historie_ordner>/abgelehnt/<Firma>/   -> Hinweis "abgelehnt"
  <historie_ordner>/<Firma>/             -> Hinweis "Ordner vorhanden"

Wie bei tracker.py ist das bewusst nur ein *weicher Hinweis* in der GUI und
setzt keine Häkchen: ein Ordner heißt nicht, dass genau diese Stelle beworben
wurde (und Ordnernamen sind Kürzel oder Tippfehler). Die Häkchen im Reiter
"Empfehlungen" bleiben deine Entscheidung.
"""
import datetime
import os
import re
from typing import Dict, List

from .schema import Job

# Teile von Ordnernamen, die keine Firma benennen ("Bewerbung_Gerrit", "Cobus_initiativ")
_KEINE_FIRMA = {"bewerbung", "initiativ", "iniativbewerbung", "initiativbewerbung", "anschreiben", "kopie"}
_MIN_LAENGE = 4  # kürzere Kürzel ("SVA", "VCG") würden zu viele Firmen treffen


def _norm(text: str) -> str:
    text = text.lower().replace("&", "und")
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    return re.sub(r"[^a-z0-9]", "", text)


def lade_historie(cfg: dict) -> List[Dict]:
    """[{"ordner": "Infosim", "status": "abgelehnt"|"ordner", "schluessel": [...], "datum": "2026-08-22"}]"""
    limits = cfg["bewerbungslimits"]
    basis = os.path.expanduser(limits.get("historie_ordner") or "")
    if not basis or not os.path.isdir(basis):
        return []
    abgelehnt_name = limits.get("historie_abgelehnt_unterordner", "abgelehnt")
    ignorieren = {n.lower() for n in limits.get("historie_ignorieren", [])} | {abgelehnt_name.lower()}
    ueberschrieben = limits.get("historie_schluessel") or {}

    eintraege: List[Dict] = []
    for status, ordner in (("ordner", basis), ("abgelehnt", os.path.join(basis, abgelehnt_name))):
        if not os.path.isdir(ordner):
            continue
        for name in sorted(os.listdir(ordner)):
            pfad = os.path.join(ordner, name)
            if not os.path.isdir(pfad) or name.lower() in ignorieren or name.startswith("."):
                continue
            if name in ueberschrieben:  # von Hand gepflegt (Tippfehler, zu allgemeine Wörter)
                schluessel = [_norm(k) for k in ueberschrieben[name] or []]
            else:
                teile = [t for t in name.split("_") if t and t.lower() not in _KEINE_FIRMA]
                # ganzer Name ("sopra_steria" -> "soprasteria") und erstes Wort ("sopra")
                schluessel = {_norm("".join(teile)), _norm(teile[0]) if teile else ""}
                schluessel = sorted(s for s in schluessel if len(s) >= _MIN_LAENGE)
            if not schluessel:
                continue
            datum = datetime.date.fromtimestamp(os.path.getmtime(pfad)).isoformat()
            eintraege.append({"ordner": name, "status": status, "schluessel": schluessel, "datum": datum})
    return eintraege


def hinweis(job: Job, historie: List[Dict]) -> str:
    """Kurzer Text für die GUI ("" wenn nichts bekannt). Absagen haben Vorrang."""
    firma = _norm(job.company)
    treffer = [h for h in historie if any(s in firma for s in h["schluessel"])]
    if not treffer:
        return ""
    treffer.sort(key=lambda h: h["status"] != "abgelehnt")
    h = treffer[0]
    if h["status"] == "abgelehnt":
        return f"früher abgelehnt ({h['ordner']}, {h['datum']})"
    return f"Ordner vorhanden: {h['ordner']} ({h['datum']})"
