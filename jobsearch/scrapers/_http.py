"""Gemeinsame HTTP-Hilfsfunktion für die HTML-Scraper (Stepstone, Indeed).

Kein eigener Quellen-Scraper (kein NAME/search_all) - nur intern von den
site-spezifischen Modulen genutzt, damit User-Agent & Anfrage-Logik nicht
doppelt gepflegt werden müssen.
"""
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}


def get(url: str, delay: float) -> str:
    time.sleep(delay)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text
