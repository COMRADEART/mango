"""Stamp promotion_floors.json recorded_at with the real clock."""
import json
from datetime import datetime, timezone
from pathlib import Path

p = Path("evaluations/t15/promotion_floors.json")
doc = json.loads(p.read_text(encoding="utf-8"))
doc["recorded_at"] = datetime.now(timezone.utc).isoformat()
p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print("stamped", doc["recorded_at"])
