import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from aicu.detection import baseline
from aicu.topics import topic_analysis
from aicu.pipeline import prepare_records, run_pipeline
from aicu.semantic import validate_decisions
from aicu.space import SpaceInspector, incoming_clues
from aicu.desktop_service import open_local_report
from tests.test_core import record


class TopicRegressionTests(unittest.TestCase):
    def test_public_discussion_examples_and_war_contrast(self):
        cases = [
            ("某女权账号的成分", {"topic_politics", "topic_gender"}),
            ("我为什么不用自杀式无人机", {"topic_politics", "topic_military"}),
            ("自杀式无人机不更好吗？", {"topic_politics", "topic_military"}),
            ("许三观一辈子卖的血还没美国副总统一年卖的血多。[大哭][大哭]", {"topic_politics"}),
            ("飞沫计划，在旧金山喷洒病毒", {"topic_politics", "topic_military"}),
            ("@日本国驻华大使馆  也够", {"topic_politics"}),
            ("泛蒙古主义，泛突厥主义要不要也和棒子国争议一下", {"topic_politics", "topic_ethnicity"}),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(expected <= set(topic_analysis(text)["labels"]))
                self.assertNotIn("war_incitement", baseline(text)["risk_labels"])
        self.assertIn("war_incitement", baseline("应该轰炸他们的城市")["risk_labels"])

    def test_obfuscation_negation_and_nickname_contrasts(self):
        for text in ["@测试对象  也够", "你个也够", "你是ＳＢ", "傻*逼", "你就是初生"]:
            with self.subTest(text=text):
                self.assertIn("insult", baseline(text)["risk_labels"])
        for text in ["这些也够用了", "这也够好看了", "USB 接口", "出生医学证明", "回复 @傻逼名字 :谢谢", "不要骂他傻逼"]:
            with self.subTest(text=text):
                self.assertNotIn("insult", baseline(text)["risk_labels"])
        self.assertIn("ethnic_discrimination", baseline("和棒子国争议一下")["risk_labels"])
        for text in ["讨论泛蒙古主义与泛突厥主义", "不要用棒子国来称呼韩国", "韩国人写的教材"]:
            self.assertNotIn("ethnic_discrimination", baseline(text)["risk_labels"])

    def test_ambiguous_reply_requires_context_not_nickname(self):
        text = "回复 @勿谈国事 :吃不上米而已"
        analysis = topic_analysis(text)
        self.assertNotIn("topic_politics", analysis["labels"])
        self.assertEqual(analysis["candidates"][0]["label"], "topic_politics")
        self.assertFalse(topic_analysis("回复 @政治女权游戏 :谢谢")["labels"])
        class Context:
            requests = 1
            def fetch(self, r):
                return {"state": "partial", "title": "政府政策和粮食价格讨论", "conversation": [{"text": "你这个废物", "role": "other_or_unverified_author"}]}
        with tempfile.TemporaryDirectory() as temp:
            report = run_pipeline("99", [record(text)], {}, temp, fetcher=Context(), progress=lambda _: None)
            r = report["records"][0]
            self.assertEqual(report["context_review"]["attempted"], 1)
            self.assertIn("topic_politics", r["topic_labels"])
            self.assertFalse(r["topic_candidates"])
            self.assertFalse(r["assessment"]["risk_labels"])
            self.assertTrue(any(e["source"] == "source_title" for e in r["topic_evidence"]))

    def test_model_topic_evidence_must_match_claimed_source(self):
        r = prepare_records("99", [record("吃不上米而已")])[0]
        r["source_context"] = {"state": "partial", "title": "粮食与政府政策"}
        item = {"id": r["id"], "status": "no_risk_observed", "labels": [], "target": "不明", "needs_context": False,
                "reason": "讨论粮食政策", "evidence": [], "topics": [{"label": "topic_politics", "source": "source_title", "quote": "政府政策", "reason": "视频话题"}]}
        good, bad = validate_decisions(json.dumps({"items": [item]}), [r])
        self.assertTrue(good)
        item["topics"][0]["source"] = "text"
        good, bad = validate_decisions(json.dumps({"items": [item]}), [r])
        self.assertFalse(good)
        self.assertTrue(bad)

    def test_source_topics_ignore_unrelated_siblings_and_emojis(self):
        ctx = {"state": "available", "title": "饮食观察", "conversation": [
            {"is_root": True, "text": "油盐摄入讨论"},
            {"is_parent": True, "text": "建议看看各国肥胖率和人均寿命数据"},
            {"role": "other_or_unverified_author", "text": "原神游戏动漫音乐大礼包"}]}
        result = topic_analysis("吃不上米而已", source_context=ctx)
        self.assertIn("topic_politics", result["labels"])
        self.assertNotIn("topic_game", result["labels"])
        self.assertNotIn("topic_anime", result["labels"])
        self.assertFalse(result["candidates"])
        self.assertNotIn("topic_politics", topic_analysis("我喜欢日本美食")["labels"])
        self.assertNotIn("topic_game", topic_analysis("[原神_喜欢]")["labels"])

    def test_windows_report_open_uses_native_path(self):
        with tempfile.TemporaryDirectory(prefix="报告 路径 ") as temp:
            path = Path(temp) / "report.html"
            path.write_text("test")
            with patch("aicu.desktop_service.os.startfile", create=True) as start, patch("aicu.desktop_service.os.name", "nt"):
                open_local_report(path)
                start.assert_called_once_with(str(path.resolve()))


def post(dynamic_id="100", mid="99"):
    return {"id_str": dynamic_id, "type": "DYNAMIC_TYPE_WORD", "modules": {"module_author": {"mid": mid}}}


def reply(rid, mid, text, parent="0", children=None, count=0):
    return {"rpid_str": rid, "member": {"mid": mid}, "content": {"message": text}, "parent_str": parent,
            "replies": children or [], "rcount": count}


class FixtureFetcher:
    def __init__(self, feed, comments):
        self.feed, self.comments, self.urls = feed, comments, []

    def read(self, url):
        self.urls.append(url)
        parsed = urlsplit(url)
        if "feed/space" in parsed.path:
            return self.feed(parse_qs(parsed.query)) if callable(self.feed) else self.feed
        return self.comments(parsed.path, parse_qs(parsed.query)) if callable(self.comments) else self.comments


class SpaceRegressionTests(unittest.TestCase):
    def test_incoming_markers_and_attacks_are_separate_from_owner(self):
        roots = [reply("1", "88", "家访[doge]"), reply("2", "99", "你这个废物"),
                 reply("3", "77", "讨论", children=[reply("4", "88", "你这个废物", "3")]),
                 reply("5", "99", "欢迎", children=[reply("6", "88", "你这个废物", "5")])]
        fetcher = FixtureFetcher({"items": [post()], "has_more": False}, {"replies": roots, "page": {"count": 4}})
        inspector = SpaceInspector(fetcher)
        with tempfile.TemporaryDirectory() as temp:
            report = run_pipeline("99", [record("谢谢")], {}, temp, source_limit=0, space_limit=10,
                                  space_inspector=inspector, progress=lambda _: None)
        space = report["space_review"]
        self.assertEqual(space["status"], "clues_found")
        self.assertEqual({o["rpid"] for o in space["observations"]}, {"1", "6"})
        self.assertEqual(report["stats"]["records"], 1)
        self.assertFalse(report["records"][0]["assessment"]["risk_labels"])
        self.assertFalse(report["stats"]["labels"])

    def test_unavailable_and_changed_schema_are_unknown_not_clean(self):
        class Blocked:
            def read(self, url):
                raise RuntimeError("HTTP 412")
        result = SpaceInspector(Blocked()).inspect("99")
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["coverage"]["request_count"], 1)
        malformed = FixtureFetcher({"items": [post()], "has_more": False}, {})
        result = SpaceInspector(malformed).inspect("99")
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["errors"])

    def test_benign_marker_mentions_and_unknown_targets_not_claimed(self):
        for text in ["老师今天家访", "标记菜谱", "标记一下重点", "别去家访他", "请不要网暴他"]:
            self.assertFalse(incoming_clues(text), text)
        for text in ["标记", "恍然大悟", "来家访了", "看完主页恍然大悟"]:
            self.assertTrue(incoming_clues(text), text)
        node = reply("1", "88", "@其他访客 你这个废物")
        fetcher = FixtureFetcher({"items": [post(), post("101", "55")], "has_more": False}, {"replies": [node], "page": {"count": 1}})
        result = SpaceInspector(fetcher).inspect("99")
        self.assertFalse(result["observations"])
        self.assertEqual(result["coverage"]["unsupported_posts"], 1)
        self.assertEqual(len(fetcher.urls), 2)

    def test_feed_and_nested_pagination_request_budget_and_cancel(self):
        def feed(params):
            if params.get("offset") == ["next"]:
                return {"items": [post("101")], "has_more": False}
            return {"items": [post()], "has_more": True, "offset": "next"}
        def comments(path, params):
            if path.endswith("reply/reply"):
                return {"replies": [reply("2", "88", "家访", "1")]}
            if params["oid"] == ["100"]:
                return {"replies": [reply("1", "99", "欢迎", count=1)], "page": {"count": 1}}
            return {"replies": [], "page": {"count": 0}}
        fetcher = FixtureFetcher(feed, comments)
        result = SpaceInspector(fetcher).inspect("99")
        self.assertEqual(result["coverage"]["feed_pages"], 2)
        self.assertEqual(result["coverage"]["thread_pages"], 1)
        self.assertEqual(result["observations"][0]["rpid"], "2")
        result = SpaceInspector(FixtureFetcher(feed, comments)).inspect("99", max_requests=1)
        self.assertEqual(result["coverage"]["request_count"], 1)
        self.assertEqual(result["status"], "unknown")
        cancel = threading.Event()
        cancel.set()
        result = SpaceInspector(fetcher).inspect("99", cancel=cancel)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["coverage"]["request_count"], 0)

    def test_repeated_cursor_stops_and_missing_author_not_attributed(self):
        fetcher = FixtureFetcher({"items": [post(mid="")], "has_more": True, "offset": "same"}, {})
        result = SpaceInspector(fetcher).inspect("99")
        self.assertTrue(result["errors"])
        self.assertEqual(result["coverage"]["reply_pages"], 0)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(len(fetcher.urls), 2)

    def test_pinned_clue_survives_later_thread_failure(self):
        def comments(path, params):
            if path.endswith("reply/reply"):
                raise RuntimeError("HTTP 412")
            return {"replies": [], "top": {"upper": reply("1", "88", "家访", count=30)}, "page": {"count": 1}}
        result = SpaceInspector(FixtureFetcher({"items": [post()], "has_more": False}, comments)).inspect("99")
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["status"], "clues_found")
        self.assertEqual(result["observations"][0]["rpid"], "1")
        self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
