import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aicu.cli import main
from aicu.collector import parse_page
from aicu.detection import baseline, topic_tags
from aicu.pipeline import aggregate, prepare_records, run_pipeline
from aicu.report import render_report
from aicu.context import ContextFetcher, allowed_url, source_link
from aicu.semantic import validate_decisions


def record(text, rpid="1"):
    return {"type":"comment", "text":text, "time":"2026-01-01T01:00:00+08:00", "context":"", "reference":"123", "raw":{"rpid":rpid,"dyn":{"type":1,"oid":"123"}}}


class RegressionTests(unittest.TestCase):
    def test_language_contrasts(self):
        cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(text=case["text"]):
                decision = baseline(case["text"])
                self.assertTrue(set(case["expected"]) <= set(decision["risk_labels"]))
                self.assertFalse(set(case["forbidden"]) & set(decision["risk_labels"]))
                self.assertNotIn("positive", decision)
                self.assertFalse(decision["model_checked"])

    def test_nonmatching_is_unreviewed_and_ascii_boundaries(self):
        self.assertEqual(baseline("我喜欢这个视频")["status"], "unreviewed")
        self.assertNotIn("topic_tech", topic_tags("daily vlog"))

    def test_parse_all_types_and_reject_changed_schema(self):
        for kind, data in [("comment",{"replies":[{"message":"hi","time":1710000000}]}),("video",{"videodmlist":[{"content":"hi","ctime":1710000000}]}),("live",{"list":[{"roominfo":{"roomid":"1"},"danmu":[{"text":"hi","ts":1710000000}]}]})]:
            self.assertEqual(parse_page(kind,{"code":0,"data":data})[0][0]["text"],"hi")
        with self.assertRaises(ValueError): parse_page("comment",{"code":0,"data":{}})

    def test_context_url_and_author_attribution(self):
        self.assertFalse(allowed_url("https://www.bilibili.com.evil.test/video/1"))
        self.assertFalse(allowed_url("https://www.bilibili.com@evil.test/"))
        self.assertFalse(allowed_url("http://www.bilibili.com/"))
        r=prepare_records("99",[record("你这个废物")])[0]
        self.assertIn("#reply1",source_link(r))
        fetcher=ContextFetcher(delay=0)
        def fake_read(url,as_json=True):
            if not as_json:return "<title>原页面标题</title>"
            if "/view?" in url:return {"title":"视频标题","desc":"简介","tname":"动画"}
            return {"root":{"rpid":"1","member":{"mid":"88"},"content":{"message":"其他人的评论"}}}
        with patch.object(fetcher,"read",side_effect=fake_read): ctx=fetcher.fetch(r)
        self.assertEqual(ctx["state"],"partial")
        self.assertFalse(ctx["target_found"])
        self.assertEqual(ctx["conversation"][0]["role"],"other_or_unverified_author")

    def test_structured_model_validation(self):
        r=prepare_records("99",[record("你这个废物")])[0]
        item={"id":r["id"],"status":"risk","labels":["insult"],"target":"对话对象","needs_context":False,"reason":"直接辱骂","evidence":[{"label":"insult","quote":"废物","reason":"贬损对方"}]}
        good,bad=validate_decisions(json.dumps({"items":[item]}),[r])
        self.assertTrue(good[r["id"]]["model_checked"])
        item["evidence"][0]["quote"]="原文不存在的脏话"
        good,bad=validate_decisions(json.dumps({"items":[item]}),[r])
        self.assertFalse(good);self.assertIn(r["id"],bad)
        good,bad=validate_decisions('{"items":[]}',[r]);self.assertFalse(good);self.assertTrue(bad)

    def test_context_failure_keeps_candidate_and_export_escapes_script(self):
        class Fetcher:
            requests=1
            def fetch(self,r):return {"state":"unavailable","errors":["HTTP 403"]}
        with tempfile.TemporaryDirectory() as temp:
            report=run_pipeline("99",[record("妈妈的处女是我的啦[喜欢]</script><script>alert(1)</script>")],{},temp,source_limit=1,fetcher=Fetcher(),progress=lambda x:None)
            r=report["records"][0]
            self.assertEqual(r["assessment"]["status"],"suspected")
            self.assertEqual(r["source_context"]["state"],"unavailable")
            page=render_report(report)
            self.assertNotIn("</script><script>alert(1)</script>",page)
            self.assertIn("\\u003c/script",page)
            self.assertNotIn("积极表达占比",page)

    def test_dedup_and_share_denominator(self):
        records=prepare_records("99",[record("原神玩家都是脑残"),record("原神玩家都是脑残"),record("喜欢音乐","2")])
        self.assertEqual(len(records),2)
        report=aggregate(records)
        self.assertAlmostEqual(sum(x["share"] for x in report["labels"]),1)
        self.assertTrue(all(x["count"]<=2 for x in report["labels"]))

    def test_offline_cli_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("urllib.request.OpenerDirector.open",side_effect=AssertionError("demo must not use network")):
                self.assertEqual(main(["--demo","--out",temp]),0)
            directory=Path(temp)/"demo"
            self.assertTrue((directory/"report.html").exists())
            self.assertTrue((directory/"llm_requests.jsonl").exists())
            report=json.loads((directory/"report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["stats"]["semantic_reviewed"],0)


if __name__=="__main__":unittest.main()
