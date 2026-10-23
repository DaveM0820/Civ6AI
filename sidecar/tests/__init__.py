"""Unittest discover: keep seat memory out of the repo root."""
from __future__ import annotations

import os
import tempfile

if not os.environ.get("CIV6AI_MEMORY_DIR"):
    os.environ["CIV6AI_MEMORY_DIR"] = tempfile.mkdtemp(prefix="civ6ai-memory-")
