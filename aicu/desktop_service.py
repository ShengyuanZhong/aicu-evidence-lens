"""Settings and background jobs used by the desktop interface."""
import json
import os
from pathlib import Path
from .cli import load_input
from .collector import collect
from .pipeline import run_pipeline
from .report import render_report
from .semantic import ModelClient

def config_file():
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "AicuEvidenceLens" / "settings.json"


def read_settings(path=None):
    try:
        value = json.loads((path or config_file()).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(value, path=None):
    target = path or config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    safe = {k: value[k] for k in ("output", "model_url", "model_name", "use_model", "max_pages", "source_limit", "llm_record_limit") if k in value}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def run_job(options, progress, cancel):
    uid, out = options["uid"], Path(options["output"])
    client = ModelClient(options["model_url"], options["model_name"], api_key=options["api_key"]) if options["use_model"] and not options["demo"] else None
    if options["demo"]:
        records, coverage = load_input(Path(__file__).parent.parent / "examples" / "demo.json")
    elif options["input_file"]:
        path = Path(options["input_file"])
        records, coverage = load_input(path, path.suffix.lower() == ".jsonl")
        if any("uid" in r and str(r["uid"]) != uid for r in records):
            raise ValueError("导入文件中的 UID 与当前输入不一致")
    else:
        records, coverage = collect(uid, 100, options["max_pages"], 1, 15, 2, progress=progress, cancel=cancel)
    directory = out / uid
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = run_pipeline(uid, records, coverage, directory, client=client, source_limit=0 if options["demo"] else options["source_limit"],
                          llm_limit=options["llm_record_limit"], progress=progress, cancel=cancel, demo=options["demo"])
    path = directory / "report.html"
    path.write_text(render_report(report), encoding="utf-8")
    return path, report
