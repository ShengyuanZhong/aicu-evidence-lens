"""Native Windows UI for querying, model settings and opening reports."""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .cli import load_input
from .collector import collect
from .pipeline import run_pipeline
from .report import render_report
from .semantic import ModelClient

BG = "#edf2f7"
INK = "#173149"
MUTED = "#607488"
BLUE = "#2465bb"
WHITE = "#ffffff"


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


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aicu 发言观察")
        self.geometry("1020x760")
        self.minsize(850, 680)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_report = None
        self.exit_when_done = False
        settings = read_settings()
        default_output = str(Path.home() / "Documents" / "Aicu报告")
        self.uid = tk.StringVar()
        self.input_file = tk.StringVar()
        self.output = tk.StringVar(value=settings.get("output", default_output))
        self.max_pages = tk.StringVar(value=str(settings.get("max_pages", 0)))
        self.source_limit = tk.StringVar(value=str(settings.get("source_limit", 30)))
        self.llm_record_limit = tk.StringVar(value=str(settings.get("llm_record_limit", 0)))
        self.use_model = tk.BooleanVar(value=bool(settings.get("use_model", False)))
        self.model_url = tk.StringVar(value=settings.get("model_url", ""))
        self.model_name = tk.StringVar(value=settings.get("model_name", ""))
        self.api_key = tk.StringVar()
        self._build()
        self.after(120, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TEntry", padding=7, fieldbackground=WHITE)
        style.configure("TButton", padding=(14, 9), font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", background=BLUE, foreground=WHITE, borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#174f9a"), ("disabled", "#9eacc0")])
        style.configure("TCheckbutton", background=WHITE, foreground=INK, font=("Microsoft YaHei UI", 10))
        style.configure("TProgressbar", troughcolor="#dfe8f1", background=BLUE)
        header = tk.Frame(self, bg=INK, padx=30, pady=21)
        header.pack(fill="x")
        tk.Label(header, text="AICU · EVIDENCE LENS", fg="#8fbbee", bg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(header, text="公开发言观察台", fg=WHITE, bg=INK, font=("Microsoft YaHei UI", 23, "bold")).pack(anchor="w", pady=(6, 1))
        tk.Label(header, text="输入 UID，追溯证据，再阅读有覆盖说明的分析报告。", fg="#cad9e8", bg=INK, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        body = tk.Frame(self, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        query = self._card(body, 0, "01  查询与来源")
        model = self._card(body, 1, "02  模型配置")
        self._field(query, "Bilibili UID", self.uid)
        self._field(query, "已有数据文件（可选 .json / .jsonl）", self.input_file, browse=self._choose_input)
        self._field(query, "报告保存位置", self.output, browse=self._choose_output)
        advanced = tk.Frame(query, bg=WHITE)
        advanced.pack(fill="x", pady=(4, 0))
        self._small_field(advanced, "每类最多页数 · 0=全部", self.max_pages, 0)
        self._small_field(advanced, "来源核查上限", self.source_limit, 1)
        tk.Label(query, text="来源核查只访问 Bilibili；无法读取的页面会在报告中注明。", bg=WHITE, fg=MUTED, wraplength=390, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(14, 0))
        ttk.Checkbutton(model, text="启用逐条模型审核与最终评述", variable=self.use_model).pack(anchor="w", pady=(4, 9))
        self._field(model, "Chat Completions 接口地址", self.model_url)
        self._field(model, "模型名称", self.model_name)
        self._field(model, "API Key · 仅当前进程使用", self.api_key, secret=True)
        self._field(model, "最多审核条数 · 0=全部", self.llm_record_limit)
        ttk.Button(model, text="测试模型连接", command=self._test_model).pack(anchor="w", pady=(2, 5))
        tk.Label(model, text="启用模型后，发言原文与取得的来源上下文会发送至所填接口。接口与模型名可保存，密钥不会保存。", bg=WHITE, fg=MUTED, wraplength=390, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 0))
        lower = tk.Frame(body, bg=WHITE, padx=20, pady=16, highlightbackground="#dbe5ee", highlightthickness=1)
        lower.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(18, 0))
        body.rowconfigure(1, weight=1)
        actions = tk.Frame(lower, bg=WHITE)
        actions.pack(fill="x")
        self.run_button = ttk.Button(actions, text="开始分析", style="Accent.TButton", command=self._start)
        self.run_button.pack(side="left")
        self.demo_button = ttk.Button(actions, text="生成演示报告", command=lambda: self._start(demo=True))
        self.demo_button.pack(side="left", padx=(9, 0))
        self.stop_button = ttk.Button(actions, text="停止", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=(9, 0))
        self.open_button = ttk.Button(actions, text="打开报告", command=self._open, state="disabled")
        self.open_button.pack(side="right")
        self.progress = ttk.Progressbar(lower, mode="indeterminate")
        self.progress.pack(fill="x", pady=(16, 8))
        self.status = tk.StringVar(value="就绪 · 可先生成合成演示报告")
        tk.Label(lower, textvariable=self.status, bg=WHITE, fg=INK, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.log = ScrolledText(lower, height=8, bg="#f7f9fc", fg="#34506a", font=("Consolas", 9), relief="flat", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(9, 0))
        self.log.configure(state="disabled")

    def _card(self, parent, column, title):
        outer = tk.Frame(parent, bg=WHITE, padx=20, pady=17, highlightbackground="#dbe5ee", highlightthickness=1)
        outer.grid(row=0, column=column, sticky="nsew", padx=(0, 9) if column == 0 else (9, 0))
        tk.Label(outer, text=title, bg=WHITE, fg=INK, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(0, 14))
        return outer

    def _field(self, parent, label, variable, browse=None, secret=False):
        box = tk.Frame(parent, bg=WHITE)
        box.pack(fill="x", pady=(0, 12))
        tk.Label(box, text=label, bg=WHITE, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 5))
        row = tk.Frame(box, bg=WHITE)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=variable, show="•" if secret else "").pack(side="left", fill="x", expand=True)
        if browse:
            ttk.Button(row, text="浏览", command=browse).pack(side="left", padx=(6, 0))

    def _small_field(self, parent, label, variable, column):
        box = tk.Frame(parent, bg=WHITE)
        box.grid(row=0, column=column, sticky="ew", padx=(0, 7) if column == 0 else (7, 0))
        parent.columnconfigure(column, weight=1)
        tk.Label(box, text=label, bg=WHITE, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 5))
        ttk.Entry(box, textvariable=variable).pack(fill="x")

    def _choose_input(self):
        choice = filedialog.askopenfilename(title="选择已有记录", filetypes=[("JSON 数据", "*.json *.jsonl"), ("所有文件", "*.*")])
        if choice:
            self.input_file.set(choice)

    def _choose_output(self):
        choice = filedialog.askdirectory(title="选择报告保存目录")
        if choice:
            self.output.set(choice)

    def _settings(self):
        return {"output": self.output.get().strip(), "model_url": self.model_url.get().strip(), "model_name": self.model_name.get().strip(),
                "use_model": self.use_model.get(), "max_pages": int(self.max_pages.get()), "source_limit": int(self.source_limit.get()),
                "llm_record_limit": int(self.llm_record_limit.get())}

    def _job_options(self, demo=False):
        settings = self._settings()
        if min(settings["max_pages"], settings["source_limit"], settings["llm_record_limit"]) < 0:
            raise ValueError("页数、来源上限和模型审核上限不能为负数")
        if not settings["output"]:
            raise ValueError("请选择报告保存位置")
        uid = "demo" if demo else self.uid.get().strip()
        if not demo and not re.fullmatch(r"[1-9]\d{0,19}", uid):
            raise ValueError("请输入有效的数字 UID")
        if settings["use_model"] and not demo and (not settings["model_url"] or not settings["model_name"]):
            raise ValueError("启用模型时需填写接口地址和模型名称")
        settings.update(uid=uid, input_file=self.input_file.get().strip(), api_key=self.api_key.get(), demo=demo)
        return settings

    def _append_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self, demo=False):
        if self.worker and self.worker.is_alive():
            return
        try:
            options = self._job_options(demo)
            write_settings(options)
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法开始", str(exc), parent=self)
            return
        self.cancel.clear()
        self.status.set("正在生成报告…")
        self._append_log("开始：" + ("合成演示" if demo else "UID " + options["uid"]))
        self.run_button.configure(state="disabled")
        self.demo_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(12)

        def work():
            try:
                path, report = run_job(options, lambda text: self.events.put(("log", text)), self.cancel)
                self.events.put(("done", (path, report)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _test_model(self):
        endpoint, name, key = self.model_url.get().strip(), self.model_name.get().strip(), self.api_key.get()
        if not endpoint or not name:
            messagebox.showerror("配置不完整", "请填写模型接口地址和模型名称。", parent=self)
            return
        self._append_log("测试模型连接…（仅发送测试文字，不发送发言数据）")

        def work():
            try:
                client = ModelClient(endpoint, name, api_key=key, timeout=15)
                answer = client.complete([{"role": "user", "content": "请只回复 OK"}])
                self.events.put(("test", "连接成功，模型返回：" + answer[:120]))
            except Exception as exc:
                self.events.put(("test", "连接失败：" + str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "test":
                    self._append_log(payload)
                elif kind == "done":
                    path, report = payload
                    self.last_report = path
                    self.open_button.configure(state="normal")
                    self.progress.stop()
                    self.run_button.configure(state="normal")
                    self.demo_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("已停止并保存部分报告" if report["run_state"] == "cancelled" else "报告已生成")
                    self._append_log(str(path))
                    self._append_log(f"记录 {report['stats']['records']} 条 · 标签命中 {report['stats']['label_assignments']} 次 · 模型已审 {report['stats']['semantic_reviewed']} 条")
                    if self.exit_when_done:
                        self.destroy()
                        return
                elif kind == "error":
                    self.progress.stop()
                    self.run_button.configure(state="normal")
                    self.demo_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("运行失败")
                    self._append_log("失败：" + payload)
                    if self.exit_when_done:
                        self.destroy()
                        return
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _open(self):
        if self.last_report and self.last_report.exists():
            webbrowser.open(self.last_report.resolve().as_uri())

    def _stop(self):
        self.cancel.set()
        self.status.set("正在停止，当前请求结束后保存已取得的数据…")

    def _close(self):
        if self.worker and self.worker.is_alive():
            self.exit_when_done = True
            self._stop()
        else:
            self.destroy()


def launch():
    MainWindow().mainloop()
