#!/usr/bin/env python3
"""Summarise out/drc.json: counts per type, then every non-silkscreen item."""
import json
import os
from collections import Counter

d = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "drc.json")))
print(dict(Counter(v["type"] for v in d["violations"])), "unrouted", len(d["unconnected_items"]),
      "parity", len(d.get("schematic_parity", [])))
for v in d["violations"]:
    if not v["type"].startswith("silk"):
        print(" ", v["type"], " | ".join(f"{i['description']} @({i['pos']['x'] - 100:.2f},{i['pos']['y'] - 100:.2f})"
                                          for i in v["items"]))
