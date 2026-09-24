"""Civ V minimap: odd-r hex with terrain sprites, territory, fog, icons, and settle rings."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sidecar.map_render_civ6 import render_civ6_map_png


def render_civ5_map_for_model(snapshot: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Civ V uses the same hex renderer as Civ VI (square Civ IV cells misplace rivers and coast)."""
    return render_civ6_map_png(snapshot, path, prefer_civ5_sprites=True)
