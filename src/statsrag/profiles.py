from __future__ import annotations
import json
from pathlib import Path
from typing import Tuple, List, Dict, Any

def load_profile(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def merge_profiles(philosophy: Dict[str, Any], probability: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    prohibitions = []
    required = []
    for p in [philosophy, probability]:
        prohibitions.extend(p.get("prohibitions", []))
        required.extend(p.get("required_reporting", []))
    def dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return dedup(prohibitions), dedup(required)
