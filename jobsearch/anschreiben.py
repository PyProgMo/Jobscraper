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
import os
from typing import List

import requests

from .schema import Job

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


def _lade_beispiele(beispiel_ordner: str) -> List[str]:
    if not os.path.isdir(beispiel_ordner):
        return []
    beispiele = []
    for name in sorted(os.listdir(beispiel_ordner)):
        if name.lower() == "readme.txt":
            continue
        if name.lower().endswith((".txt", ".md")):
            pfad = os.path.join(beispiel_ordner, name)
            with open(pfad, "r", encoding="utf-8") as f:
                inhalt = f.read().strip()
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
