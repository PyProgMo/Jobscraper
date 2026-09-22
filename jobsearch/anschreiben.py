"""Erzeugt einen KI-Prompt für ein individuelles Bewerbungsanschreiben aus
einer Stellenanzeige und den eigenen Beispiel-Anschreiben (siehe
Anschreiben_Beispiele/README.txt), und kann diesen Prompt optional direkt
über einen OpenAI-kompatiblen Chat-Completions-Endpunkt generieren lassen
(z.B. einen lokalen llama.cpp-Server).

Modulares Anbieter-Konzept (siehe config.yaml unter 'anschreiben.anbieter'):
  - typ "browser": der Aufrufer (gui.py) kopiert den Prompt in die
    Zwischenablage und öffnet die Anbieter-URL im Browser - keine
    Netzwerklogik hier nötig.
  - typ "api_openai_kompatibel": generate_via_api() ruft den Endpunkt direkt
    auf und liefert den fertigen Anschreiben-Text zurück.
Weitere Anbieter-Typen lassen sich hier ergänzen, ohne die GUI anzufassen.
"""
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from typing import List

import requests

from .schema import Job

log = logging.getLogger(__name__)

_ODT_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"

PROMPT_TEMPLATE = """Du bist ein professioneller Bewerbungsschreiber. Schreibe ein individuelles, überzeugendes Bewerbungsanschreiben für folgende Stelle:

Titel: {title}
Firma: {company}
Ort: {location}
Quelle: {source}

Stellenbeschreibung:
{description}

{beispiele_hinweis}
{beispiele_block}

Gib ausschließlich den fertigen Anschreiben-Text aus, ohne Erklärungen davor oder danach."""


def _odt_zu_text(pfad: str) -> str:
    """Liest den Fließtext aus einer OpenDocument-Text-Datei (.odt, z.B. von
    LibreOffice/OpenOffice) - das Format ist ein ZIP-Archiv mit einer
    content.xml, die die Absätze als <text:p>-Elemente enthält."""
    with zipfile.ZipFile(pfad) as zf:
        with zf.open("content.xml") as f:
            baum = ET.parse(f)
    absaetze = [
        "".join(p.itertext()) for p in baum.getroot().iter(f"{{{_ODT_TEXT_NS}}}p")
    ]
    return "\n".join(absaetze).strip()


def _lade_beispiele(beispiel_ordner: str) -> List[str]:
    if not os.path.isdir(beispiel_ordner):
        return []
    beispiele = []
    for name in sorted(os.listdir(beispiel_ordner)):
        if name.lower() == "readme.txt":
            continue
        pfad = os.path.join(beispiel_ordner, name)
        endung = name.lower().rsplit(".", 1)[-1] if "." in name else ""

        try:
            if endung in ("txt", "md"):
                with open(pfad, "r", encoding="utf-8") as f:
                    inhalt = f.read().strip()
            elif endung == "odt":
                inhalt = _odt_zu_text(pfad)
            else:
                continue
        except Exception as exc:
            log.warning("Beispiel-Anschreiben konnte nicht gelesen werden (%s): %s", name, exc)
            continue

        if inhalt:
            beispiele.append(inhalt)
    return beispiele


def build_prompt(job: Job, beispiel_ordner: str) -> str:
    beispiele = _lade_beispiele(beispiel_ordner)
    if beispiele:
        beispiele_hinweis = (
            "Orientiere dich beim Ton, Aufbau und persönlichen Schreibstil an "
            "folgenden eigenen Beispiel-Anschreiben (Inhalte nicht wörtlich "
            "übernehmen, sondern nur den Stil treffen):"
        )
        beispiele_block = "\n\n".join(
            f"--- Beispiel {i + 1} ---\n{text}" for i, text in enumerate(beispiele)
        )
    else:
        beispiele_hinweis = (
            "Es liegen keine Beispiel-Anschreiben vor - schreibe in einem "
            "professionellen, aber persönlichen Standardstil."
        )
        beispiele_block = ""

    return PROMPT_TEMPLATE.format(
        title=job.title,
        company=job.company,
        location=job.location or "unbekannt",
        source=job.source,
        description=job.description.strip() or "(keine Beschreibung verfügbar - bitte allgemein auf Titel und Firma eingehen)",
        beispiele_hinweis=beispiele_hinweis,
        beispiele_block=beispiele_block,
    ).strip()


def generate_via_api(prompt: str, anbieter_cfg: dict) -> str:
    """Ruft einen OpenAI-kompatiblen Chat-Completions-Endpunkt auf und gibt
    den generierten Anschreiben-Text zurück."""
    base_url = anbieter_cfg["base_url"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    api_key = anbieter_cfg.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": anbieter_cfg.get("modell", "local-model"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    resp = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
