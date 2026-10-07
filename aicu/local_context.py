"""Bounded context from the same author's nearby live messages, never other rooms."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime


def attach_nearby(records, seconds=180, limit=4):
    groups = defaultdict(list)
    for r in records:
        r["nearby_author"] = []
        if r["type"] != "live" or not str(r["reference"]).isdigit():
            continue
        try:
            when = datetime.fromisoformat(r["time"])
            if when.tzinfo is None:
                continue
            stamp = when.timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        groups[(r["uid"], r["reference"])].append((stamp, r))
    for group in groups.values():
        group.sort(key=lambda x: (x[0], x[1]["id"]))
        times = [t for t, _ in group]
        for stamp, r in group:
            left, right = bisect_left(times, stamp - seconds), bisect_right(times, stamp + seconds)
            # Exact repetition does not resolve the meaning of an ambiguous phrase.
            peers = [v for t, v in sorted(group[left:right], key=lambda x: abs(x[0] - stamp)) if v["id"] != r["id"] and v["text"] != r["text"]]
            seen = set()
            for v in peers:
                if v["text"] in seen:
                    continue
                seen.add(v["text"])
                r["nearby_author"].append({"id": v["id"], "uid": v["uid"], "text": v["text"], "time": v["time"], "reference": v["reference"], "role": "same_author_nearby"})
                if len(r["nearby_author"]) >= limit:
                    break
