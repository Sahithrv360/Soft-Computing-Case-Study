"""Placeholder for later export to an identified removable storage path."""
from pathlib import Path

class SDLogExporter:
    def export(self, database: Path, destination: Path) -> None:
        raise NotImplementedError("SQLite currently stores on the configured filesystem; SD path is unconfigured")
