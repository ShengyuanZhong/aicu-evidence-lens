"""Responsive desktop interface with explicit, readable control states."""
from __future__ import annotations

import os
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .desktop_service import config_file, read_settings, run_job, write_settings
from .semantic import ModelClient

BG = "#f3f5f7"
WHITE = "#ffffff"
INK = "#182c3b"
MUTED = "#647583"
LINE = "#dde4e9"
ACCENT = "#087f73"
SIDEBAR = "#132b36"
FONT = "Microsoft YaHei UI"


class ActionButton(tk.Button):
    """Use explicit colors for every state, independent of the OS theme."""
    PALETTES = {
        "primary": (ACCENT, "#ffffff", "#06695f"),
        "secondary": ("#eaf0f3", INK, "#dce7ed"),
        "quiet": (WHITE, "#405765", "#edf3f5"),
        "nav": (SIDEBAR, "#c4d3da", "#1f3e4b"),
        "selected": ("#24515a", "#ffffff", "#2b5e67"),
    }

    def __init__(self, parent, text, command, kind="secondary", **kwargs):
        self.kind = kind
        self.palette = self.PALETTES[kind]
        bg, fg, hover = self.palette
        super().__init__(parent, text=text, command=command, font=(FONT, 10),
                         bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                         disabledforeground="#60727d", relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=bg, highlightcolor=ACCENT,
                         padx=16, pady=10, cursor="hand2", takefocus=True, **kwargs)
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<Return>", lambda _: self.invoke())

    def _hover(self, entered):
        if str(self.cget("state")) != "disabled":
            self.configure(bg=self.palette[2] if entered else self.palette[0])

    def set_enabled(self, enabled):
        self.configure(state="normal" if enabled else "disabled",
                       bg=self.palette[0] if enabled else "#e8edf0",
                       fg=self.palette[1], disabledforeground="#657782",
                       cursor="hand2" if enabled else "arrow")

    def set_selected(self, selected):
        self.palette = self.PALETTES["selected" if selected else "nav"]
        self.configure(bg=self.palette[0], fg=self.palette[1],
                       activebackground=self.palette[2], activeforeground=self.palette[1],
                       highlightbackground=self.palette[0])


class ScrollPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner = tk.Frame(self.canvas, bg=BG, padx=28, pady=24)
        self.item = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.inner.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def wheel(self, delta):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta, "units")


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aicu 发言观察")
        width = min(1120, self.winfo_screenwidth() - 60)
        height = min(820, self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.minsize(min(840, width), min(600, height))
        self.configure(bg=BG)
        self.option_add("*Font", (FONT, 10))
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.busy = False
        self.test_busy = False
        self.last_report = None
        self.exit_when_done = False
        self.started_at = None
        self.input_controls = []
        self.buttons = []
        self.nav = {}
        self.pages = {}
        self.metric_values = []
        settings = read_settings()
        self.uid = tk.StringVar()
        self.source_mode = tk.StringVar(value="online")
        self.input_file = tk.StringVar()
        self.output = tk.StringVar(value=settings.get("output") or str(Path.home() / "Documents" / "Aicu报告"))
        self.max_pages = tk.StringVar(value=str(settings.get("max_pages", 0)))
        self.source_limit = tk.StringVar(value=str(settings.get("source_limit", 30)))
        self.llm_record_limit = tk.StringVar(value=str(settings.get("llm_record_limit", 0)))
        self.use_model = tk.BooleanVar(value=bool(settings.get("use_model", False)))
        self.model_url = tk.StringVar(value=settings.get("model_url", ""))
        self.model_name = tk.StringVar(value=settings.get("model_name", ""))
        self.api_key = tk.StringVar()
        self.status = tk.StringVar(value="准备就绪")
        self.detail = tk.StringVar(value="输入 UID 开始分析，或先查看演示报告。")
        self.elapsed = tk.StringVar(value="")
        self.model_status = tk.StringVar(value="填写配置后，可以先测试连接。")
        self.report_path = tk.StringVar(value="报告生成后，可在这里打开或查看保存位置。")
        self.mode_description = tk.StringVar()
        self.mode_badge = tk.StringVar()
        self._build()
        self.use_model.trace_add("write", self._update_mode)
        self.model_name.trace_add("write", self._update_mode)
        self._update_mode()
        self._switch_page("query")
        self.bind("<MouseWheel>", self._on_wheel, add="+")
        self.bind("<Control-Return>", lambda _: self._start())
        self.bind("<Control-s>", lambda _: self._save_configuration())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._drain_timer = self.after(80, self._drain)

    def _button(self, parent, text, command, kind="secondary", **kwargs):
        button = ActionButton(parent, text, command, kind, **kwargs)
        self.buttons.append(button)
        return button

    def _text(self, parent, text=None, size=10, color=INK, bold=False, variable=None, wrap=False):
        label = tk.Label(parent, text=text, textvariable=variable, bg=parent.cget("bg"), fg=color,
                         font=(FONT, size, "bold" if bold else "normal"), anchor="w", justify="left")
        if wrap:
            parent.bind("<Configure>", lambda e: label.configure(wraplength=max(180, e.width - 44)), add="+")
            label.configure(wraplength=600)
        return label

    def _card(self, parent, title, subtitle=None):
        outer = tk.Frame(parent, bg=WHITE, padx=22, pady=19, highlightbackground=LINE, highlightthickness=1)
        outer.pack(fill="x", pady=(0, 16))
        self._text(outer, title, 12, bold=True).pack(anchor="w", pady=(0, 6))
        if subtitle:
            self._text(outer, subtitle, 9, MUTED, wrap=True).pack(fill="x", pady=(0, 13))
        return outer

    def _entry(self, parent, label, variable, hint=None, browse=None, secret=False):
        field = tk.Frame(parent, bg=parent.cget("bg"))
        field.pack(fill="x", pady=(5, 12))
        self._text(field, label, 10, bold=True).pack(anchor="w", pady=(0, 7))
        row = tk.Frame(field, bg=field.cget("bg"))
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=variable, style="Field.TEntry",
                          font=(FONT, 11), show="*" if secret else "")
        entry.pack(side="left", fill="x", expand=True, ipady=2)
        entry.bind("<Control-a>", lambda _: (entry.selection_range(0, "end"), "break")[-1])
        self.input_controls.append(entry)
        if browse:
            button = self._button(row, "选择文件" if variable is self.input_file else "更改目录", browse)
            button.pack(side="right", padx=(10, 0))
            self.input_controls.append(button)
        if hint:
            self._text(field, hint, 9, MUTED, wrap=True).pack(fill="x", pady=(6, 0))
        return entry, row

    def _check(self, parent, text, variable):
        control = tk.Checkbutton(parent, text=text, variable=variable, bg=parent.cget("bg"),
                                 fg=INK, activebackground=parent.cget("bg"), activeforeground=INK,
                                 selectcolor=WHITE, disabledforeground="#657782", anchor="w",
                                 font=(FONT, 10), padx=0, pady=5, cursor="hand2")
        self.input_controls.append(control)
        return control

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Field.TEntry", padding=(10, 8), fieldbackground=WHITE,
                        foreground=INK, insertcolor=INK, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.map("Field.TEntry", foreground=[("disabled", "#657782")],
                  fieldbackground=[("disabled", "#f0f3f5")], bordercolor=[("focus", ACCENT)])
        style.configure("App.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e4ecee",
                        borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = tk.Frame(self, bg=SIDEBAR, width=190, padx=18, pady=26)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.pack_propagate(False)
        self._text(sidebar, "AICU", 24, "#ffffff", True).pack(anchor="w")
        self._text(sidebar, "EVIDENCE LENS", 9, "#89b9b5").pack(anchor="w", pady=(2, 30))
        for key, title in [("query", "开始分析"), ("model", "模型配置"), ("activity", "运行记录")]:
            button = self._button(sidebar, title, lambda k=key: self._switch_page(k), "nav", anchor="w")
            button.pack(fill="x", pady=4)
            self.nav[key] = button
        bottom = tk.Frame(sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x")
        self._text(bottom, variable=self.mode_badge, size=10, color="#a3d9cd").pack(anchor="w")
        self._text(bottom, "本地工作台", 9, "#8fa8b4").pack(anchor="w", pady=(10, 3))
        self._text(bottom, "v" + __version__, 9, "#8fa8b4").pack(anchor="w")
        workspace = tk.Frame(self, bg=BG)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(1, weight=1)
        self.notice = tk.Frame(workspace, bg="#fff0e9", padx=22, pady=12)
        self.notice.grid(row=0, column=0, sticky="ew")
        self.notice_text = self._text(self.notice, "", 10, "#9d452e", wrap=True)
        self.notice_text.pack(fill="x")
        self.notice.grid_remove()
        stack = tk.Frame(workspace, bg=BG)
        stack.grid(row=1, column=0, sticky="nsew")
        stack.columnconfigure(0, weight=1)
        stack.rowconfigure(0, weight=1)
        for key in self.nav:
            page = ScrollPage(stack)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self._build_query(self.pages["query"].inner)
        self._build_model(self.pages["model"].inner)
        self._build_activity(self.pages["activity"].inner)
        self._build_footer(workspace)

    def _page_heading(self, parent, title, subtitle):
        self._text(parent, title, 22, bold=True).pack(anchor="w", pady=(0, 6))
        self._text(parent, subtitle, 10, MUTED, wrap=True).pack(fill="x", pady=(0, 22))

    def _build_query(self, parent):
        self._page_heading(parent, "从公开发言开始", "查询或导入记录，查看内容分布与需要核查的表达。")
        card = self._card(parent, "01  账号与数据")
        self.uid_entry, _ = self._entry(card, "Bilibili UID", self.uid, "填写账号的数字 UID，例如 123456。")
        modes = tk.Frame(card, bg=WHITE)
        modes.pack(fill="x", pady=(0, 9))
        for value, title in [("online", "在线查询"), ("import", "导入本地文件")]:
            control = tk.Radiobutton(modes, text=title, variable=self.source_mode, value=value,
                                     command=self._toggle_source, bg=WHITE, fg=INK, activebackground=WHITE,
                                     activeforeground=INK, selectcolor=WHITE, disabledforeground=MUTED,
                                     font=(FONT, 10), cursor="hand2")
            control.pack(side="left", padx=(0, 22))
            self.input_controls.append(control)
        self.import_box = tk.Frame(card, bg=WHITE)
        self.input_entry, _ = self._entry(self.import_box, "数据文件", self.input_file,
                                          "支持 JSON、JSONL 和已有 report.json。", browse=self._choose_input)
        self.source_hint = self._text(card, "在线查询将采集评论、视频弹幕与直播弹幕。", 9, MUTED, wrap=True)
        self.source_hint.pack(fill="x")
        card = self._card(parent, "02  报告与审核")
        self.output_entry, _ = self._entry(card, "报告保存目录", self.output, browse=self._choose_output)
        self._check(card, "使用模型进行逐条语义审核", self.use_model).pack(anchor="w")
        self._text(card, variable=self.mode_description, size=9, color=MUTED, wrap=True).pack(fill="x", pady=(0, 9))
        self._button(card, "前往模型配置", lambda: self._switch_page("model"), "quiet").pack(anchor="w")
        self.advanced_button = self._button(card, "展开采集选项", self._toggle_advanced, "quiet")
        self.advanced_button.pack(anchor="w", pady=(14, 0))
        self.advanced_box = tk.Frame(card, bg=WHITE)
        self._entry(self.advanced_box, "每类最多采集页数", self.max_pages, "0 表示全部；限制页数可以减少等待。")
        self._entry(self.advanced_box, "最多核查来源条数", self.source_limit, "默认 30 条；设为 0 可关闭 Bilibili 来源核查。")

    def _build_model(self, parent):
        self._page_heading(parent, "模型配置", "连接兼容 Chat Completions 的服务，对原文进行语义审核。")
        card = self._card(parent, "模型服务")
        self._check(card, "在分析时启用模型", self.use_model).pack(anchor="w", pady=(0, 6))
        self.url_entry, _ = self._entry(card, "接口地址", self.model_url,
                                       "填写完整地址，例如 https://服务地址/v1/chat/completions。")
        self.name_entry, _ = self._entry(card, "模型名称", self.model_name, "使用服务商提供的模型 ID。")
        self.key_entry, row = self._entry(card, "API Key", self.api_key,
                                          "密钥仅保留在本次会话中，不会保存到磁盘。", secret=True)
        self.key_button = self._button(row, "显示密钥", self._toggle_key, "quiet")
        self.key_button.pack(side="right", padx=(10, 0))
        self._entry(card, "最多审核条数", self.llm_record_limit, "0 表示全部；其余记录在报告中保留未审核状态。")
        actions = tk.Frame(card, bg=WHITE)
        actions.pack(fill="x", pady=(5, 12))
        self.test_button = self._button(actions, "测试连接", self._test_model)
        self.test_button.pack(side="left")
        self.save_button = self._button(actions, "保存配置", self._save_configuration, "primary")
        self.save_button.pack(side="left", padx=(10, 0))
        self._text(card, variable=self.model_status, size=10, color=MUTED, wrap=True).pack(fill="x")
        card = self._card(parent, "数据如何使用")
        self._text(card, "启用后，发言原文与取得的来源上下文会发送至你填写的接口。"
                   "本机服务支持 http://127.0.0.1:端口/v1/chat/completions；远程服务使用 HTTPS。",
                   9, MUTED, wrap=True).pack(fill="x")

    def _build_activity(self, parent):
        self._page_heading(parent, "运行记录", "查看进度、处理结果和当前任务的运行信息。")
        card = self._card(parent, "最近一次结果")
        metrics = tk.Frame(card, bg=WHITE)
        metrics.pack(fill="x", pady=(5, 16))
        for i, title in enumerate(["发言记录", "标签命中", "模型已审"]):
            metrics.columnconfigure(i, weight=1, uniform="metrics")
            cell = tk.Frame(metrics, bg=WHITE)
            cell.grid(row=0, column=i, sticky="ew")
            value = tk.StringVar(value="—")
            self.metric_values.append(value)
            self._text(cell, variable=value, size=25, color=ACCENT, bold=True).pack(anchor="w")
            self._text(cell, title, 9, MUTED).pack(anchor="w")
        self._text(card, variable=self.report_path, size=9, color=MUTED, wrap=True).pack(fill="x", pady=(0, 10))
        self.folder_button = self._button(card, "打开报告目录", self._open_folder)
        self.folder_button.pack(anchor="w")
        self.folder_button.set_enabled(False)
        card = self._card(parent, "任务日志", "日志自动更新；向上滚动查看时会保持当前位置。")
        self.log = ScrolledText(card, height=11, bg="#f7f9fa", fg="#3d5563",
                               font=(FONT, 10), relief="flat", bd=0, padx=12, pady=12, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self._button(card, "复制日志", self._copy_log, "quiet").pack(anchor="w", pady=(12, 0))

    def _build_footer(self, parent):
        footer = tk.Frame(parent, bg=WHITE, padx=26, pady=16, highlightthickness=1, highlightbackground=LINE)
        footer.grid(row=2, column=0, sticky="ew")
        state_row = tk.Frame(footer, bg=WHITE)
        state_row.pack(fill="x")
        self._text(state_row, variable=self.status, size=11, bold=True).pack(side="left")
        self._text(state_row, variable=self.elapsed, size=9, color=MUTED).pack(side="right")
        self._text(footer, variable=self.detail, size=9, color=MUTED, wrap=True).pack(fill="x", pady=(4, 8))
        self.progress = ttk.Progressbar(footer, style="App.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 13))
        actions = tk.Frame(footer, bg=WHITE)
        actions.pack(fill="x")
        self.demo_button = self._button(actions, "查看演示", lambda: self._start(demo=True), "quiet")
        self.demo_button.pack(side="left")
        self.stop_button = self._button(actions, "停止分析", self._stop)
        self.stop_button.pack(side="left", padx=(8, 0))
        self.run_button = self._button(actions, "开始分析", self._start, "primary")
        self.run_button.pack(side="right")
        self.open_button = self._button(actions, "打开报告", self._open)
        self.open_button.pack(side="right", padx=(0, 8))
        self._refresh_actions()

    def _switch_page(self, key):
        self.current_page = key
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
            self.nav[name].set_selected(name == key)

    def _on_wheel(self, event):
        if isinstance(event.widget, tk.Text):
            return
        widget = event.widget
        while widget is not None:
            if widget is self.pages[self.current_page]:
                self.pages[self.current_page].wheel(-1 if event.delta > 0 else 1)
                return "break"
            widget = getattr(widget, "master", None)

    def _toggle_source(self):
        if self.source_mode.get() == "import":
            self.import_box.pack(fill="x", before=self.source_hint)
            self.source_hint.configure(text="导入时会保留原文，并重新生成分析报告。")
        else:
            self.import_box.pack_forget()
            self.source_hint.configure(text="在线查询将采集评论、视频弹幕与直播弹幕。")

    def _toggle_advanced(self):
        if self.advanced_box.winfo_manager():
            self.advanced_box.pack_forget()
            self.advanced_button.configure(text="展开采集选项")
        else:
            self.advanced_box.pack(fill="x", pady=(8, 0))
            self.advanced_button.configure(text="收起采集选项")

    def _toggle_key(self):
        visible = bool(self.key_entry.cget("show"))
        self.key_entry.configure(show="" if visible else "*")
        self.key_button.configure(text="隐藏密钥" if visible else "显示密钥")

    def _update_mode(self, *_):
        enabled = self.use_model.get()
        self.mode_badge.set("语义审核已启用" if enabled else "离线检索模式")
        self.mode_description.set(("已启用：" + (self.model_name.get().strip() or "请先填写模型配置"))
                                  if enabled else "当前使用离线规则寻找待核查线索。")

    def _show_notice(self, text):
        self.notice_text.configure(text=text)
        self.notice.grid()

    def _choose_input(self):
        choice = filedialog.askopenfilename(parent=self, title="选择已有记录",
                                            filetypes=[("JSON 数据", "*.json *.jsonl"), ("所有文件", "*.*")])
        if choice:
            self.input_file.set(choice)

    def _choose_output(self):
        choice = filedialog.askdirectory(parent=self, title="选择报告保存目录")
        if choice:
            self.output.set(choice)

    def _settings(self):
        values = {}
        for key, variable, label in [("max_pages", self.max_pages, "采集页数"),
                                      ("source_limit", self.source_limit, "来源核查上限"),
                                      ("llm_record_limit", self.llm_record_limit, "模型审核条数")]:
            try:
                values[key] = int(variable.get().strip())
            except ValueError:
                raise ValueError(label + "需要填写非负整数，0 表示不限制或关闭。") from None
            if values[key] < 0:
                raise ValueError(label + "不能为负数。")
        if not self.output.get().strip():
            raise ValueError("请选择报告保存目录。")
        return dict(values, output=self.output.get().strip(), model_url=self.model_url.get().strip(),
                    model_name=self.model_name.get().strip(), use_model=self.use_model.get())

    def _job_options(self, demo=False):
        settings = self._settings()
        uid = "demo" if demo else self.uid.get().strip()
        if not demo and not re.fullmatch(r"[1-9]\d{0,19}", uid):
            self._switch_page("query")
            self.uid_entry.focus_set()
            raise ValueError("请输入有效的数字 UID。")
        input_file = self.input_file.get().strip() if self.source_mode.get() == "import" and not demo else ""
        if not demo and self.source_mode.get() == "import" and not Path(input_file).is_file():
            self._switch_page("query")
            raise ValueError("请选择存在的 JSON 或 JSONL 数据文件。")
        if settings["use_model"] and not demo:
            if not settings["model_url"] or not settings["model_name"]:
                self._switch_page("model")
                raise ValueError("启用模型时，请填写接口地址和模型名称。")
            try:
                ModelClient(settings["model_url"], settings["model_name"], api_key=self.api_key.get().strip())
            except ValueError:
                self._switch_page("model")
                raise
        return dict(settings, uid=uid, input_file=input_file, api_key=self.api_key.get().strip(), demo=demo)

    def _save_configuration(self):
        try:
            write_settings(self._settings())
            self.notice.grid_remove()
            self.model_status.set("配置已保存。API Key 仅用于本次会话。")
            self.detail.set("配置已保存，下次启动时自动恢复。")
        except (ValueError, OSError) as exc:
            self._show_notice(str(exc))

    def _refresh_actions(self):
        ready = not self.busy and not self.test_busy
        self.run_button.set_enabled(ready)
        self.demo_button.set_enabled(ready)
        self.stop_button.set_enabled(self.busy and not self.cancel.is_set())
        self.open_button.set_enabled(self.last_report is not None)
        self.test_button.set_enabled(ready)
        self.save_button.set_enabled(not self.busy)
        self.run_button.configure(text="正在分析…" if self.busy else "开始分析")
        self.stop_button.configure(text="正在停止…" if self.busy and self.cancel.is_set() else "停止分析")
        self.test_button.configure(text="正在连接…" if self.test_busy else "测试连接")

    def _set_busy(self, value):
        self.busy = value
        for control in self.input_controls:
            if isinstance(control, ActionButton):
                control.set_enabled(not value)
            else:
                control.configure(state="disabled" if value else "normal")
        self._refresh_actions()

    def _start(self, demo=False):
        if self.busy or self.test_busy:
            return
        try:
            options = self._job_options(demo)
            write_settings(options)
        except (ValueError, OSError) as exc:
            self._show_notice(str(exc))
            return
        self.notice.grid_remove()
        self.cancel.clear()
        self.started_at = time.monotonic()
        self.elapsed.set("已用时 00:00")
        self.status.set("正在生成演示" if demo else "正在分析")
        self.detail.set("正在准备数据，请稍候…")
        self._append_logs(["开始：" + ("合成演示" if demo else "UID " + options["uid"])])
        self._set_busy(True)
        self._switch_page("activity")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(16)

        def work():
            try:
                path, report = run_job(options, lambda text: self.events.put(("log", text)), self.cancel)
                self.events.put(("done", (path, report)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _test_model(self):
        if self.test_busy or self.busy:
            return
        try:
            client = ModelClient(self.model_url.get().strip(), self.model_name.get().strip(),
                                 api_key=self.api_key.get().strip(), timeout=15)
        except ValueError as exc:
            self._show_notice(str(exc))
            return
        self.notice.grid_remove()
        self.test_busy = True
        self.model_status.set("正在连接，只发送测试文字…")
        self._refresh_actions()

        def work():
            try:
                answer = client.complete([{"role": "user", "content": "请只回复 OK"}])
                result = "连接成功 · " + client.model + " · " + answer[:100]
            except Exception as exc:
                result = "连接失败：" + str(exc)
            self.events.put(("test", result))

        threading.Thread(target=work, daemon=True).start()

    def _append_logs(self, lines):
        if not lines:
            return
        at_bottom = self.log.yview()[1] >= .98
        self.log.configure(state="normal")
        self.log.insert("end", "\n".join(lines) + "\n")
        count = int(self.log.index("end-1c").split(".")[0])
        if count > 2000:
            self.log.delete("1.0", f"{count - 2000}.0")
        if at_bottom:
            self.log.see("end")
        self.log.configure(state="disabled")

    def _finish(self, path, report):
        self.last_report = path
        self.report_path.set(str(path))
        self.folder_button.set_enabled(True)
        for variable, key in zip(self.metric_values, ["records", "label_assignments", "semantic_reviewed"]):
            variable.set(str(report["stats"][key]))
        incomplete = bool(report["errors"]) or any(v.get("state") == "error" for v in report["coverage"].values())
        cancelled = report["run_state"] == "cancelled"
        self.status.set("已停止并保存" if cancelled else ("完成，部分请求失败" if incomplete else "报告已生成"))
        self.detail.set("可以打开报告查看结果和数据覆盖情况。")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0 if cancelled else 100)
        self._append_logs([self.status.get(), str(path)])
        self._set_busy(False)

    def _drain(self):
        logs = []
        # Bound each UI update so a burst of logs cannot monopolize the event loop.
        for _ in range(100):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                logs.append(payload)
                self.detail.set(payload)
            elif kind == "test":
                self.test_busy = False
                self.model_status.set(payload)
                logs.append(payload)
                self._refresh_actions()
            elif kind == "done":
                self._append_logs(logs)
                logs = []
                self._finish(*payload)
            elif kind == "error":
                self.progress.stop()
                self.progress.configure(mode="determinate", value=0)
                self.status.set("分析未完成")
                self.detail.set("请检查运行记录，修改配置后重试。")
                logs.append("失败：" + payload)
                self._show_notice(payload)
                self._set_busy(False)
        self._append_logs(logs)
        if self.started_at is not None and self.busy:
            seconds = int(time.monotonic() - self.started_at)
            self.elapsed.set(f"已用时 {seconds // 60:02d}:{seconds % 60:02d}")
        if self.exit_when_done and not self.busy:
            self.destroy()
            return
        self._drain_timer = self.after(80, self._drain)

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log.get("1.0", "end-1c"))
        self.detail.set("运行日志已复制。")

    def _open(self):
        if self.last_report and self.last_report.exists():
            webbrowser.open(self.last_report.resolve().as_uri())

    def _open_folder(self):
        if self.last_report and self.last_report.parent.exists():
            if os.name == "nt":
                os.startfile(self.last_report.parent)
            else:
                webbrowser.open(self.last_report.parent.resolve().as_uri())

    def _stop(self):
        if not self.busy:
            return
        self.cancel.set()
        self.status.set("正在停止")
        self.detail.set("当前请求结束后会保存已取得的数据，请稍候。")
        self._refresh_actions()

    def _close(self):
        if self.busy:
            self.exit_when_done = True
            self._stop()
        else:
            self.destroy()

    def destroy(self):
        if getattr(self, "_drain_timer", None):
            self.after_cancel(self._drain_timer)
            self._drain_timer = None
        super().destroy()


def launch():
    MainWindow().mainloop()
