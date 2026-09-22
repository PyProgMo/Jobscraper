"""Lädt die zentrale config.yaml des Projekts."""
import os
import yaml

# config.yaml liegt eine Ebene über diesem Package (Projekt-Wurzel)
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


def load_config(path: str = None) -> dict:
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg
