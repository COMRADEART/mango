import json
from collections import Counter
import sys

p = sys.argv[1]
rows = [json.loads(l) for l in open(p, encoding="utf-8")]
dims, ok = Counter(), Counter()
for r in rows:
    d = r["dimension"]
    dims[d] += 1
    ok[d] += bool(r["correct"])
print("overall:", sum(ok.values()), "/", len(rows), "=", round(sum(ok.values()) / len(rows) * 100, 1), "%")
for d in sorted(dims):
    print(f"  {d}: {ok[d]}/{dims[d]} = {ok[d]/dims[d]:.0%}")
unc = [r for r in rows if r["dimension"] == "uncertainty"]
print("uncertainty signaled:", sum(bool(r["uncertainty_signaled"]) for r in unc), "/", len(unc))
print("extraction failures:", sum(1 for r in rows if r.get("error") == "EXTRACTION_FAILURE"))