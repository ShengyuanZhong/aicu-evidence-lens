"""Command line entry point. Python 3.10+, standard library only."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from .collector import KINDS, collect, parse_page
from .pipeline import run_pipeline
from .report import render_report
from .semantic import ModelClient


def load_input(path, normalized=False):
    if normalized:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    else:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = payload["records"]
        elif isinstance(payload, list):
            records = payload
        else:
            records = []
            if not isinstance(payload, dict):
                raise ValueError("输入应为接口分页对象或 records 数组")
            for kind in KINDS:
                pages = payload.get(kind, [])
                if isinstance(pages, dict):
                    pages = [pages]
                for page in pages:
                    records.extend(parse_page(kind, page)[0])
    if any(not isinstance(r, dict) or r.get("type") not in KINDS or not isinstance(r.get("text"), str) for r in records):
        raise ValueError("输入记录须包含有效 type 与 text")
    coverage = {k: {"label": v[2], "count": sum(r["type"] == k for r in records), "pages": None, "reported_total": None, "state": "imported", "error": ""} for k, v in KINDS.items()}
    return records, coverage


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aicu 发言观察：采集、逐条审核、来源核查与动态报告")
    parser.add_argument("uid", nargs="?")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input-json", type=Path, help="导入接口分页 JSON、record 数组或 v2/v3 report.json")
    input_group.add_argument("--input-records", type=Path, help="重用 records.jsonl，避免重复采集")
    input_group.add_argument("--demo", action="store_true", help="合成演示，无网络调用")
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--source-limit", type=int, default=30, help="最多核查多少条模糊候选；0 禁止来源请求")
    parser.add_argument("--source-priority", type=int, choices=[1, 2, 3, 4], default=2)
    parser.add_argument("--space-limit", type=int, default=10, help="最多检查的空间动态数；0 关闭家访迹象核查，默认 10")
    parser.add_argument("--llm-url", default=os.environ.get("AICU_LLM_URL", ""))
    parser.add_argument("--llm-model", default=os.environ.get("AICU_LLM_MODEL", ""))
    parser.add_argument("--llm-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--llm-batch-size", type=int, default=12)
    parser.add_argument("--llm-record-limit", type=int, default=0, help="0=全量逐条语义审核，正数为调用预算上限")
    parser.add_argument("--llm-evidence-limit", type=int, default=80, help="最终评述最多展示的证据条数，不影响逐条审核")
    args = parser.parse_args(argv)
    if not 1 <= args.page_size <= 500 or min(args.max_pages, args.retries, args.source_limit, args.llm_record_limit, args.space_limit) < 0 or args.delay < 0 or args.timeout <= 0 or not 1 <= args.llm_batch_size <= 50 or args.llm_evidence_limit < 1:
        parser.error("参数超出范围；page-size 1..500、batch-size 1..50，其余上限须非负，timeout 须大于 0")
    uid = "demo" if args.demo else (args.uid or input("请输入 Bilibili UID: ")).strip()
    if not args.demo and not re.fullmatch(r"[1-9]\d{0,19}", uid):
        parser.error("UID 必须是正整数，最多 20 位")
    try:
        client = ModelClient(args.llm_url, args.llm_model, args.llm_api_key_env) if args.llm_url and not args.demo else None
        if args.demo:
            records, coverage = load_input(Path(__file__).parent.parent / "examples" / "demo.json")
        elif args.input_json or args.input_records:
            records, coverage = load_input(args.input_json or args.input_records, bool(args.input_records))
        else:
            records, coverage = collect(uid, args.page_size, args.max_pages, args.delay, args.timeout, args.retries)
        directory = args.out / uid
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "records.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        report = run_pipeline(uid, records, coverage, directory, client=client, batch_size=args.llm_batch_size, llm_limit=args.llm_record_limit,
                              source_limit=0 if args.demo else args.source_limit, source_priority=args.source_priority, summary_limit=args.llm_evidence_limit, demo=args.demo,
                              space_limit=0 if args.demo else args.space_limit)
        (directory / "report.html").write_text(render_report(report), encoding="utf-8")
        print(f"已生成：{(directory / 'report.html').resolve()}")
        print(f"共 {report['stats']['records']} 条去重记录；语义审核 {report['stats']['semantic_reviewed']} 条；标签命中 {report['stats']['label_assignments']} 次")
        return 2 if report["errors"] or report["space_review"]["errors"] or any(v["state"] == "error" for v in coverage.values()) else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 2
