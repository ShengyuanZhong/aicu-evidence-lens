"""Bounded, anonymous Bilibili page/context retrieval. No arbitrary model URLs."""
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ALLOWED_HOSTS = {"www.bilibili.com", "api.bilibili.com", "t.bilibili.com", "live.bilibili.com"}


def allowed_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except ValueError:
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("来源跳转到非 Bilibili 白名单地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def source_link(record):
    ref = str(record.get("reference") or "")
    if not ref.isdigit():
        return ""
    raw = record.get("raw") or {}
    kind = record["type"]
    type_id = str((raw.get("dyn") or {}).get("type", ""))
    if kind == "live":
        return "https://live.bilibili.com/" + ref
    if kind == "video" or type_id == "1":
        url = "https://www.bilibili.com/video/av" + ref
    elif kind == "comment" and type_id == "17":
        url = "https://t.bilibili.com/" + ref
    elif kind == "comment" and type_id == "12":
        url = "https://www.bilibili.com/read/cv" + ref
    else:
        return ""
    if kind == "comment":
        rpid = str(raw.get("rpid") or "")
        root = str((raw.get("parent") or {}).get("rootid") or rpid)
        if rpid.isdigit() and root.isdigit():
            url += f"?comment_on=1&comment_root_id={root}#reply{rpid}"
    elif kind == "video":
        try:
            seconds = max(0, int(raw.get("progress", 0)) // 1000)
            url += f"?t={seconds}"
        except (TypeError, ValueError):
            pass
    return url


class PageMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.description, self.in_title = "", "", False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key == "og:title":
                self.title = attrs.get("content", "")[:300]
            if key in ("description", "og:description"):
                self.description = attrs.get("content", "")[:1500]

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title = (self.title + data)[:300]


class ContextFetcher:
    def __init__(self, timeout=8, delay=0.4):
        self.timeout, self.delay = timeout, delay
        self.opener = urllib.request.build_opener(RestrictedRedirect())
        self.blocked = set()
        self.last_request = 0
        self.requests = 0
        self.video_cache = {}

    def read(self, url, as_json=True):
        if not allowed_url(url):
            raise ValueError("来源地址不在 Bilibili 白名单内")
        host = urllib.parse.urlsplit(url).hostname
        if host in self.blocked:
            raise RuntimeError("该来源服务已拒绝或限制访问，本轮停止请求")
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        self.requests += 1
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError("来源响应超过大小上限")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 412, 429):
                self.blocked.add(host)
            raise RuntimeError(f"HTTP {exc.code}") from exc
        if as_json:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("来源接口格式不正确")
            if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
                raise ValueError(f"来源接口 code={payload.get('code')}，数据不可用")
            return payload["data"]
        return body.decode("utf-8", "replace")

    def fetch(self, record):
        result = {"state": "unavailable", "url": record.get("source_url") or source_link(record), "title": "", "description": "", "area": "", "conversation": [], "target_found": False, "errors": [], "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "pages": []}
        if not result["url"]:
            result["errors"].append("没有可确认的来源链接")
            return result
        raw = record.get("raw") or {}
        type_id = str((raw.get("dyn") or {}).get("type", ""))
        aid = str(record.get("reference", ""))
        # Visit the original page: metadata only. JS-only content stays unavailable.
        try:
            metadata = PageMetadata()
            metadata.feed(self.read(result["url"], as_json=False))
            if metadata.title and not re.search(r"验证|拦截|Access Denied|验证码|安全检查", metadata.title, re.I):
                result.update(title=metadata.title, description=metadata.description)
                result["pages"].append(result["url"])
        except (RuntimeError, ValueError, OSError) as exc:
            result["errors"].append("原网页：" + str(exc)[:160])
        if record["type"] == "video" or type_id == "1":
            url = "https://api.bilibili.com/x/web-interface/view?aid=" + aid
            try:
                if aid not in self.video_cache:
                    self.video_cache[aid] = self.read(url)
                data = self.video_cache[aid]
                result.update(title=str(data.get("title", ""))[:300], description=str(data.get("desc", ""))[:1500], area=str(data.get("tname", ""))[:100])
                result["pages"].append(url)
            except (RuntimeError, ValueError, OSError) as exc:
                result["errors"].append("视频元信息：" + str(exc)[:160])
        if record["type"] == "comment" and type_id in {"1", "12", "17"}:
            rpid = str(raw.get("rpid") or "")
            root = str((raw.get("parent") or {}).get("rootid") or rpid)
            if rpid.isdigit() and root.isdigit():
                params = urllib.parse.urlencode({"type": type_id, "oid": aid, "root": root, "pn": 1, "ps": 20})
                url = "https://api.bilibili.com/x/v2/reply/reply?" + params
                try:
                    data = self.read(url)
                    replies = data.get("replies") or []
                    if not isinstance(replies, list):
                        raise ValueError("评论上下文列表格式不正确")
                    nodes = ([data["root"]] if isinstance(data.get("root"), dict) else []) + replies
                    for node in nodes:
                        if not isinstance(node, dict):
                            continue
                        rid = str(node.get("rpid_str") or node.get("rpid") or "")
                        content = str((node.get("content") or {}).get("message") or "")[:2000]
                        is_target = rid == rpid and str((node.get("member") or {}).get("mid") or node.get("mid") or "") == record.get("uid")
                        result["target_found"] |= is_target
                        role = "queried_author" if is_target else "other_or_unverified_author"
                        if content:
                            result["conversation"].append({"role": role, "text": content, "rpid": rid, "is_root": rid == root})
                    result["pages"].append(url)
                except (RuntimeError, ValueError, OSError) as exc:
                    result["errors"].append("评论上下文：" + str(exc)[:160])
        result["state"] = "available" if result["target_found"] else "partial" if result["title"] or result["conversation"] else "unavailable"
        return result
