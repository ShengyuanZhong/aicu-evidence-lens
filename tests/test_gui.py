"""Desktop workflows, widget layout and settings tests; no network required."""
import json
import tempfile
import threading
import time
import unittest
import tkinter as tk
import tkinter.font as tkfont
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from aicu.gui import MainWindow, read_settings, run_job, write_settings


class DesktopWorkflowTests(unittest.TestCase):
    @contextmanager
    def window(self, scale=None):
        original = tk.Tk.__init__
        def initialize(root, *args, **kwargs):
            original(root, *args, **kwargs)
            if scale is not None:
                root.tk.call("tk", "scaling", scale)
        with patch("aicu.gui.read_settings", return_value={}), patch.object(tk.Tk, "__init__", initialize):
            try:
                window = MainWindow()
            except tk.TclError as exc:
                self.skipTest(f"图形环境不可用：{exc}")
        try:
            yield window
        finally:
            window.destroy()

    def test_window_constructs_and_accepts_configuration(self):
        with self.window() as window:
            window.configure(bg="#edf2f7")
            window.update_idletasks()
            self.assertEqual(window.title(), "Aicu 发言观察")
            self.assertEqual(window._job_options(demo=True)["uid"], "demo")

    def test_action_text_and_layout_survive_small_window_and_large_fonts(self):
        for scale in (4 / 3, 2):
            with self.subTest(scale=scale), self.window(scale) as window:
                window.geometry("840x600")
                window.update()
                for page in ("query", "model", "activity"):
                    window._switch_page(page)
                    window.update()
                    for button in (window.run_button, window.stop_button, window.demo_button, window.open_button):
                        self.assertTrue(button.winfo_viewable())
                        text = button.cget("text")
                        self.assertTrue(text.strip())
                        self.assertGreaterEqual(button.winfo_width(), tkfont.Font(font=button.cget("font")).measure(text) + 16)
                        self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), window.winfo_rootx() + window.winfo_width())
                        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), window.winfo_rooty() + window.winfo_height())
                    self.assertGreater(window.pages[page].canvas.winfo_height(), 150)
                for button in window.buttons:
                    for enabled in (False, True):
                        button.set_enabled(enabled)
                        foreground = button.cget("fg" if enabled else "disabledforeground")
                        self.assertNotEqual(foreground, button.cget("bg"))

    def test_demo_button_completes_and_enables_report_actions(self):
        with tempfile.TemporaryDirectory() as temp, self.window() as window, patch("aicu.gui.write_settings"):
            window.output.set(temp)
            window.demo_button.invoke()
            self.assertTrue(window.busy)
            self.assertEqual(str(window.run_button.cget("state")), "disabled")
            deadline = time.monotonic() + 5
            while window.busy and time.monotonic() < deadline:
                window.update()
                time.sleep(.01)
            self.assertFalse(window.busy)
            self.assertTrue(window.last_report.is_file())
            self.assertEqual(window.metric_values[0].get(), "32")
            self.assertEqual(str(window.open_button.cget("state")), "normal")
            self.assertEqual(window.current_page, "activity")

    def test_model_connection_blocks_duplicate_requests(self):
        release = threading.Event()
        with self.window() as window, patch("aicu.gui.ModelClient") as model:
            model.return_value.model = "test-model"
            model.return_value.complete.side_effect = lambda _: (release.wait(3), "OK")[1]
            window._test_model()
            window._test_model()
            self.assertTrue(window.test_busy)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(str(window.test_button.cget("state")), "disabled")
            release.set()
            deadline = time.monotonic() + 3
            while window.test_busy and time.monotonic() < deadline:
                window.update()
                time.sleep(.01)
            self.assertFalse(window.test_busy)
            self.assertIn("连接成功", window.model_status.get())

    def test_settings_never_persist_api_key(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "settings.json"
            write_settings({"output": temp, "model_url": "https://example.test/v1/chat/completions",
                            "model_name": "example", "api_key": "private-test-key", "use_model": True}, target)
            raw = target.read_text(encoding="utf-8")
            self.assertNotIn("private-test-key", raw)
            self.assertNotIn("api_key", read_settings(target))
            self.assertEqual(read_settings(target)["model_name"], "example")

    def test_demo_job_writes_self_contained_dual_ring_report(self):
        with tempfile.TemporaryDirectory() as temp:
            options = {"uid": "demo", "output": temp, "demo": True, "input_file": "", "max_pages": 0,
                       "source_limit": 0, "llm_record_limit": 0, "use_model": False,
                       "model_url": "", "model_name": "", "api_key": ""}
            path, report = run_job(options, lambda _: None, threading.Event())
            html = path.read_text(encoding="utf-8")
            self.assertIn('id="ring-topic"', html)
            self.assertIn('id="ring-risk"', html)
            self.assertIn('id="legend-topic"', html)
            self.assertIn('id="legend-risk"', html)
            self.assertEqual(report["stats"]["records"], 32)
            self.assertEqual(json.loads((path.parent / "report.json").read_text(encoding="utf-8"))["uid"], "demo")


if __name__ == "__main__":
    unittest.main()
