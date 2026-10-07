import json
import tempfile
import unittest
from unittest.mock import patch

from aicu.context import ContextFetcher, PageMetadata
from aicu.detection import baseline
from aicu.pipeline import prepare_records, run_pipeline
from aicu.semantic import make_request
from tests.test_core import record


SEXUAL = {"sexualized", "sexual_harassment"}


def live(text, second=0, room="100", uid="99"):
    return {"type": "live", "text": text, "time": f"2026-01-01T12:{second // 60:02d}:{second % 60:02d}+08:00",
            "reference": room, "context": "合成直播间", "uid": uid}


class ExpressionTests(unittest.TestCase):
    def test_euphemisms_and_positive_emoji_do_not_hide_solicitations(self):
        for text in ["姐姐我想打", "帮我打个✈️吧", "姐姐我可不可以哒", "姐姐我想哒菲",
                     "姐姐我想稻罐[喜欢]", "妈妈我想喝木乳", "姐姐我想吃乃乃[花]", "姐姐我要喝奶", "妈妈我渴了，想喝奶",
                     "拍完可以干吗", "姐姐我想🔪你🖊️", "🖊️给🔪吗", "姐姐我想骑你", "姐姐你紧吗"]:
            with self.subTest(text=text):
                a = baseline(text)
                self.assertTrue(SEXUAL <= set(a["risk_labels"]))
                self.assertEqual(a["status"], "suspected")
                self.assertFalse(a["model_checked"])
                self.assertTrue(all(e["quote"] in text for e in a["evidence"]))
        for text in ["大车开的更爽呀", "这个干起来应该爽吧。", "想开大车，这车应该漏油吧", "让我爽的方法是🦌"]:
            self.assertIn("sexualized", baseline(text)["risk_labels"])

    def test_normal_activities_and_quoted_objections_do_not_become_sexual(self):
        for text in ["姐姐我想打王者", "姐姐我想打篮球", "姐姐我想喝牛奶", "姐姐我想喝奶茶",
                     "姐姐我想吃面", "牛奶很好喝", "出生证明怎么办", "我想挑战宝可梦道馆",
                     "医学导管护理", "帮我打个飞机模型", "拍完可以干别的吗", "拍完可以干活吗",
                     "这份工作干起来很爽", "我想开大车跑运输", "我想打飞机游戏", "画一支🖊️和一把🔪", "画了🔪和🖊️", "拿🔪削🖊️",
                     "不要对她说帮我打个✈️吧", "有人说‘帮我打个✈️吧’", "‘帮我打个✈️吧’是什么意思",
                     "回复 @姐姐我想打 :谢谢", "姐姐我想和你打排位"]:
            with self.subTest(text=text):
                self.assertFalse(SEXUAL & set(baseline(text)["risk_labels"]))

    def test_ambiguous_fragments_stay_pending_until_context_supports_them(self):
        for text in ["我要喝奶", "帮我打", "姐姐我出来了", "姐姐我想听爽的"]:
            with self.subTest(text=text):
                a = baseline(text)
                self.assertFalse(a["risk_labels"])
                self.assertTrue(a["context_candidates"])
                self.assertTrue(a["needs_context"])
        a = baseline("我要喝奶", nearby=[{"id": "r_fixture", "text": "姐姐我想稻罐"}])
        self.assertIn("sexualized", a["risk_labels"])
        self.assertEqual(a["evidence"][0]["context_source"], "nearby_author:r_fixture")
        self.assertFalse(baseline("谢谢姐姐", nearby=[{"id": "r_fixture", "text": "姐姐我想稻罐"}])["risk_labels"])

    def test_literal_context_resolves_weak_metaphors_without_declaring_safe(self):
        for text, title in [("大车开的更爽呀", "卡车驾驶评测"), ("姐姐我要喝奶", "婴儿喂养日记"),
                            ("姐姐我想道馆", "宝可梦道馆挑战"), ("拍完可以干吗", "摄影后期修图教程")]:
            with self.subTest(text=text):
                a = baseline(text, source_context={"state": "partial", "title": title})
                self.assertFalse(a["risk_labels"])
                self.assertTrue(a["literal_resolutions"])
                self.assertEqual(a["status"], "unreviewed")
        # A woman's appearance or an unrelated comment cannot introduce a sex label.
        self.assertFalse(baseline("好看", source_context={"state": "partial", "title": "车模摄影", "conversation": [{"text": "姐姐我想稻罐", "is_root": True}]})["risk_labels"])

    def test_nearby_context_is_bounded_by_room_time_and_exact_repetition(self):
        rs = prepare_records("99", [live("姐姐我想稻罐"), live("我要喝奶", 30), live("我要喝奶", 40, "200"), live("我要喝奶", 360), live("今天喝牛奶", 50)])
        self.assertIn("sexualized", rs[1]["assessment"]["risk_labels"])
        self.assertFalse(rs[2]["assessment"]["risk_labels"])
        self.assertFalse(rs[3]["assessment"]["risk_labels"])
        self.assertFalse(rs[4]["assessment"]["risk_labels"])
        self.assertTrue(all(n["reference"] == rs[1]["reference"] for n in rs[1]["nearby_author"]))
        repeated = prepare_records("99", [live("我要喝奶"), live("我要喝奶", 10)])
        self.assertTrue(all(not r["assessment"]["risk_labels"] for r in repeated))
        self.assertTrue(all(not r["nearby_author"] for r in repeated))
        payload = json.loads(make_request(rs)[1]["content"])
        self.assertTrue(payload["items"][1]["nearby_author"])

    def test_context_refresh_removes_weak_false_positive_and_keeps_audit(self):
        class Fixture:
            requests = 1
            def fetch(self, r):
                return {"state": "partial", "title": "卡车驾驶技巧"}
        with tempfile.TemporaryDirectory() as temp:
            report = run_pipeline("99", [record("大车开的更爽呀")], {}, temp, fetcher=Fixture(), progress=lambda _: None)
        result = report["records"][0]
        self.assertFalse(result["assessment"]["risk_labels"])
        self.assertEqual(result["audit"][-1]["stage"], "rules_with_context")
        self.assertIn("sexualized", result["audit"][-1]["before"]["risk_labels"])

    def test_insult_aliases_and_medical_mentions(self):
        for text in ["你就是🦈🖊️", "都是🦈🖊️", "队友垃圾", "纯舰🖊️", "你脑子不行", "逗傻子玩"]:
            self.assertIn("insult", baseline(text)["risk_labels"], text)
        for text in ["精神病学课本", "这是精神病的科普", "医院的精神病医生", "我没带脑子出门"]:
            self.assertNotIn("insult", baseline(text)["risk_labels"], text)


class SourceCoverageTests(unittest.TestCase):
    def test_draw_comments_use_real_comment_api_and_check_authorship(self):
        raw = record("帮我打个✈️吧")
        raw["raw"]["dyn"]["type"] = 11
        r = prepare_records("99", [raw])[0]
        fetcher = ContextFetcher(delay=0)
        data = {"root": {"rpid": "1", "mid": "99", "content": {"message": raw["text"]}}, "replies": None}
        with patch.object(fetcher, "read", return_value=data) as read:
            ctx = fetcher.fetch(r)
        self.assertIn("type=11", r["source_url"])
        read.assert_called_once()
        self.assertTrue(ctx["target_found"])
        self.assertEqual(ctx["conversation"][0]["role"], "queried_author")

    def test_current_live_homepage_is_not_historical_evidence(self):
        r = prepare_records("99", [live("姐姐我想打")])[0]
        fetcher = ContextFetcher(delay=0)
        with patch.object(fetcher, "read", side_effect=AssertionError("Must not fetch current live page")):
            ctx = fetcher.fetch(r)
        self.assertTrue(ctx["historical_unavailable"])
        self.assertEqual(ctx["state"], "unavailable")

    def test_missing_meta_content_is_handled(self):
        parser = PageMetadata()
        parser.feed('<meta property="og:title" content><meta name="description" content><title>正常标题</title>')
        self.assertEqual(parser.title, "正常标题")
        self.assertEqual(parser.description, "")


if __name__ == "__main__":
    unittest.main()
