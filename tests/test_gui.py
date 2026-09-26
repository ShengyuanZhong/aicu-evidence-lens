"""Desktop workflow tests that do not require a display or network."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from aicu.gui import read_settings, run_job, write_settings


class DesktopWorkflowTests(unittest.TestCase):
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
