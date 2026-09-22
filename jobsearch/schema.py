"""Datenmodell für eine Stellenanzeige im gemeinsamen Such-Pool."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


def _make_id(source: str, external_id: str) -> str:
    raw = f"{source}:{external_id}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str                 # "ba" | "adzuna" | "stepstone" | "indeed"
    external_id: str            # ID/Referenznummer der Quelle
    description: str = ""
    date_posted: str = ""       # Datum als String, falls von der Quelle geliefert
    remote: Optional[bool] = None

    # wird von der Pipeline befüllt, nicht beim Scrapen selbst
    id: str = field(default="", init=False)
    score: float = field(default=0.0, init=False)
    score_breakdown: dict = field(default_factory=dict, init=False)
    merged_sources: list = field(default_factory=list, init=False)
    status: str = field(default="new", init=False)  # new | applied | capped | skipped | moeglich_beworben
    first_seen: float = field(default_factory=time.time, init=False)

    def __post_init__(self):
        self.id = _make_id(self.source, self.external_id)
        self.merged_sources = [self.source]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Job":
        job = Job(
            title=d["title"], company=d["company"], location=d["location"],
            url=d["url"], source=d["source"], external_id=d["external_id"],
            description=d.get("description", ""), date_posted=d.get("date_posted", ""),
            remote=d.get("remote"),
        )
        job.id = d.get("id", job.id)
        job.score = d.get("score", 0.0)
        job.score_breakdown = d.get("score_breakdown", {})
        job.merged_sources = d.get("merged_sources", job.merged_sources)
        job.status = d.get("status", "new")
        job.first_seen = d.get("first_seen", job.first_seen)
        return job
