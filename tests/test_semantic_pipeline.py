import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from aicu.pipeline import run_pipeline
from aicu.semantic import ModelClient
from tests.test_core import record


class SemanticPipelineTests(unittest.TestCase):
    def test_reviews_unflagged_and_revisits_with_context(self):
        class FakeModel:
            endpoint="http://localhost/test"
            model="fixture-model"
            batches=[]
            def complete(self,messages):
                data=json.loads(messages[-1]["content"])
                if "items" not in data:return "本例共两条发言，需结合引用语境核查。"
                self.batches.append(data["items"])
                output=[]
                for r in data["items"]:
                    suspicious="天才" in r["text"] and r["context"]["state"]=="not_requested"
                    output.append({"id":r["id"],"status":"suspected" if suspicious else "no_risk_observed","labels":["sarcasm"] if suspicious else [],"needs_context":suspicious,"target":"不明","reason":"语境决定反讽是否针对现实人物","evidence":[{"label":"sarcasm","quote":"天才","reason":"可能反讽"}] if suspicious else []})
                return json.dumps({"items":output},ensure_ascii=False)
        class Context:
            requests=1
            def fetch(self,r):return {"state":"partial","title":"合成引用语境","conversation":[],"target_found":False}
        client=FakeModel()
        with tempfile.TemporaryDirectory() as temp:
            report=run_pipeline("99",[record("你可真是个天才"),record("谢谢","2")],{},temp,client=client,fetcher=Context(),progress=lambda x:None)
            self.assertEqual(len(client.batches[0]),2)
            self.assertEqual(len(client.batches[1]),1)
            self.assertEqual(report["stats"]["semantic_reviewed"],2)
            self.assertFalse(report["records"][0]["assessment"]["risk_labels"])
            self.assertEqual(report["records"][0]["audit"][-1]["stage"],"with_context")
            self.assertEqual(report["errors"],[])

    def test_malformed_model_output_does_not_become_safe(self):
        class BrokenModel:
            endpoint="http://localhost/test"
            model="fixture-model"
            def complete(self,messages):return '{"items":[]}'
        with tempfile.TemporaryDirectory() as temp:
            report=run_pipeline("99",[record("你是废物")],{},temp,client=BrokenModel(),source_limit=0,progress=lambda x:None)
            self.assertEqual(report["records"][0]["assessment"]["status"],"suspected")
            self.assertEqual(report["stats"]["semantic_reviewed"],0)
            self.assertTrue(report["errors"])

    def test_chat_completions_transport(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                content=json.dumps({"choices":[{"message":{"content":"收到 "+body["model"]}}]},ensure_ascii=False).encode()
                self.send_response(200);self.send_header("Content-Length",str(len(content)));self.end_headers();self.wfile.write(content)
            def log_message(self,*args):pass
        server=HTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=ModelClient(f"http://127.0.0.1:{server.server_port}/v1/chat/completions","test-model")
            self.assertEqual(client.complete([{"role":"user","content":"hi"}]),"收到 test-model")
        finally:server.shutdown();server.server_close();thread.join()
