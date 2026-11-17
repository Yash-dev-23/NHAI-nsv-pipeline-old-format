"""Identity of one silver run. Stages read this and return new frames. No globals."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RunContext:
    zone: str
    phase: str
    cycle: str
    upc: str
    config_dir: Path
    pipeline: dict
    irc: dict
    bronze_root: str = ""
    silver_root: str = ""
    tracker_path: str = ""
    image_root: str = ""
    run_date: str = ""
    run_id: str = ""
    frames: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def partition(self) -> dict[str, str]:
        return {"upc": self.upc, "phase": self.phase, "cycle": self.cycle}
