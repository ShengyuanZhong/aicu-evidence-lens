"""Review every record, fetch context for ambiguous candidates, then revisit."""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
from .context import ContextFetcher, source_link
from .detection import baseline
from .topics import topic_analysis
from .space import SpaceInspector, empty_review
from .semantic import make_request, review_batch, summarize, SYSTEM, PROMPT_VERSION
from .taxonomy import CATALOG


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def prepare_records(uid, records):
    prepared, seen = [], set()
    for r in records:
        if r.get("type") not in {"comment", "video", "live"} or not isinstance(r.get("text"), str) or not r["text"].strip():
            continue
        raw = r.get("raw") or {}
        primary = raw.get("rpid") if r["type"] == "comment" else raw.get("id")
        identity = [uid, r["type"], str(primary)] if primary else [uid, r["type"], str(r.get("reference", "")), r.get("time", ""), r["text"], r.get("context", "")]
        rid = "r_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:16]
        if rid in seen:
            continue
        seen.add(rid)
        item = {"id": rid, "uid": uid, "type": r["type"], "text": r["text"], "time": r.get("time", ""), "context": r.get("context", ""), "reference": str(r.get("reference", "")), "raw": raw}
        item.update(source_url=source_link(item), source_context={"state": "not_requested"}, assessment=baseline(item["text"]), audit=[], errors=[])
        refresh_topics(item)
        prepared.append(item)
    return prepared


def refresh_topics(record):
    result = topic_analysis(record["text"], record["context"], record["source_context"])
    model = record["assessment"]
    evidence = result["evidence"] + [{**e, "method": PROMPT_VERSION} for e in model.get("topics", [])]
    labels = list(dict.fromkeys(e["label"] for e in evidence))
    rule_candidates = result["candidates"]
    if model.get("topic_reviewed") and not model["needs_context"] and record["source_context"].get("state") in {"partial", "available"}:
        rule_candidates = []
    pending = [e for e in rule_candidates + model.get("uncertain_topics", []) if e["label"] not in labels]
    pending = list({e["label"]: e for e in pending}.values())
    record.update(topic_labels=labels, topic_evidence=evidence, topic_candidates=pending,
                  topic_needs_context=bool(pending or result["needs_context"]))


def aggregate(records):
    labels = collections.Counter()
    states = collections.Counter()
    for r in records:
        states.update([r["assessment"]["status"]])
        labels.update(set(r["topic_labels"] + r["assessment"]["risk_labels"]))
    assignments = sum(labels.values())
    return {"records": len(records), "by_type": dict(collections.Counter(r["type"] for r in records)), "states": dict(states),
            "semantic_reviewed": sum(r["assessment"]["model_checked"] for r in records),
            "label_assignments": assignments,
            "labels": [{"id": k, "name": CATALOG[k]["name"], "kind": CATALOG[k]["kind"], "count": v, "share": v / assignments if assignments else 0, "coverage": v / len(records) if records else 0} for k, v in labels.most_common()]}


def run_pipeline(uid, raw_records, coverage, directory, client=None, batch_size=12, llm_limit=0, source_limit=30, source_priority=2, summary_limit=80, progress=print, fetcher=None, demo=False, cancel=None, space_limit=0, space_inspector=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = prepare_records(uid, raw_records)
    cache_path = directory / "review_cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    errors = []
    requests_log = directory / "llm_requests.jsonl"
    requests_log.write_text("", encoding="utf-8")

    def model_pass(selected, stage):
        for start in range(0, len(selected), batch_size):
            if cancel and cancel.is_set():
                break
            group = selected[start:start + batch_size]
            with requests_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"stage": stage, "messages": make_request(group)}, ensure_ascii=False) + "\n")
            if not client:
                continue
            pending, keys = [], {}
            for r in group:
                stable_context = {k: v for k, v in r["source_context"].items() if k != "fetched_at"}
                fingerprint = [client.endpoint, client.model, SYSTEM, r["text"], r["type"], r["context"], stable_context]
                key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                keys[r["id"]] = key
                # Cache contains already validated decisions generated by this program.
                cached = cache.get(key)
                valid_cache = isinstance(cached, dict) and cached.get("method") == PROMPT_VERSION and all(k in cached for k in ("status", "risk_labels", "priority", "needs_context", "target", "reason", "evidence", "model_checked"))
                if valid_cache and isinstance(cached["risk_labels"], list) and all(k in CATALOG and CATALOG[k]["kind"] == "risk" for k in cached["risk_labels"]):
                    r["audit"].append({"stage": stage + "_cached", "before": r["assessment"]})
                    r["assessment"] = cached
                else:
                    pending.append(r)
            if pending:
                try:
                    accepted, failed = review_batch(client, pending)
                except (RuntimeError, ValueError, TypeError) as exc:
                    accepted, failed = {}, {r["id"]: str(exc) for r in pending}
                for r in pending:
                    if r["id"] in accepted:
                        r["audit"].append({"stage": stage, "before": r["assessment"]})
                        r["assessment"] = accepted[r["id"]]
                        cache[keys[r["id"]]] = r["assessment"]
                    else:
                        message = f"{stage}: {failed.get(r['id'], '无有效结果')}"
                        r["errors"].append(message)
                        errors.append({"record_id": r["id"], "error": message})
                write_json(cache_path, cache)
            for r in group:
                refresh_topics(r)
            progress(f"语义审核 {stage}: {min(start + batch_size, len(selected))}/{len(selected)}")

    selected = records[:llm_limit] if llm_limit else records
    model_pass(selected, "initial")
    def context_priority(r):
        return max(r["assessment"]["priority"] if r["assessment"]["needs_context"] else 0,
                   2 if r["topic_needs_context"] or r["assessment"]["needs_context"] else 0)
    candidates = sorted([r for r in records if context_priority(r) >= source_priority], key=context_priority, reverse=True)
    fetcher = fetcher or ContextFetcher()
    fetched = []
    for index, r in enumerate(candidates):
        if cancel and cancel.is_set():
            break
        if index >= source_limit:
            r["source_context"] = {"state": "budget_skipped", "reason": "达到来源核查数量上限"}
            continue
        r["source_context"] = fetcher.fetch(r)
        refresh_topics(r)
        fetched.append(r)
        progress(f"来源核查: {index + 1}/{min(len(candidates), source_limit)} · {r['source_context']['state']}")
    # Revisit only model-selected records with new, useful context.
    eligible = {r["id"] for r in selected}
    revisit = [r for r in fetched if r["id"] in eligible and r["source_context"]["state"] in {"available", "partial"}]
    model_pass(revisit, "with_context")
    context_requests = getattr(fetcher, "requests", 0)
    space_review = empty_review(uid)
    if space_limit and not demo:
        space_review = (space_inspector or SpaceInspector(fetcher)).inspect(uid, max_posts=space_limit, progress=progress, cancel=cancel)
    summary, summary_error = "", ""
    if client and not (cancel and cancel.is_set()):
        try:
            summary = summarize(client, records, coverage, summary_limit, space_review)
        except (RuntimeError, ValueError) as exc:
            summary_error = str(exc)
            errors.append({"stage": "summary", "error": summary_error})
    report = {"schema_version": 3, "uid": uid, "demo": demo, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "coverage": coverage,
              "catalog": CATALOG, "records": records, "stats": aggregate(records), "summary": summary, "summary_error": summary_error,
              "mode": "semantic" if client else "offline", "run_state": "cancelled" if cancel and cancel.is_set() else "complete", "errors": errors,
              "context_review": {"eligible": len(candidates), "attempted": len(fetched), "request_count": context_requests},
              "space_review": space_review,
              "limits": {"llm_records_limit": llm_limit, "context_records_limit": source_limit, "summary_evidence_limit": summary_limit},
              "deduplicated_or_empty": len(raw_records) - len(records)}
    write_json(directory / "report.json", report)
    write_json(directory / "risk_findings.json", [r for r in records if r["assessment"]["risk_labels"]])
    write_json(directory / "space_observations.json", space_review)
    (directory / "llm_review.txt").write_text(summary or ("模型评述未生成。" + summary_error), encoding="utf-8")
    return report
