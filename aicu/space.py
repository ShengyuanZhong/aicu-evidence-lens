"""Bounded inspection of incoming public comments on the queried account's posts.

This is a separate observation stream, never evidence of the owner's conduct.
No authentication, access-control bypass, or browser storage is used.
"""
import datetime as dt
import re
from urllib.parse import urlencode
from .context import ContextFetcher
from .detection import baseline
from .topics import normalize_text, without_mentions

API = "https://api.bilibili.com"
ATTACK_LABELS = {"insult", "sexual_harassment", "threat", "doxxing", "harassment",
                 "gender_hostility", "group_hostility", "ethnic_discrimination"}


def numeric(value):
    value = str(value or "")
    return value if re.fullmatch(r"[1-9][0-9]{0,24}", value) else ""


def empty_review(uid):
    return {"state": "not_requested", "status": "not_requested", "url": f"https://space.bilibili.com/{uid}/dynamic",
            "fetched_at": "", "observations": [], "errors": [], "coverage": {}, "limits": {}}


def comment_ref(item):
    """Prefer explicit comment metadata. Fail closed for unsupported post types."""
    basic = item.get("basic") or {}
    kind, oid = numeric(basic.get("comment_type")), numeric(basic.get("comment_id_str") or basic.get("comment_id"))
    if kind in {"1", "11", "12", "17"} and oid:
        return kind, oid
    major = ((item.get("modules") or {}).get("module_dynamic") or {}).get("major") or {}
    kind = item.get("type")
    if kind in {"DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_FORWARD"}:
        return "17", numeric(item.get("id_str"))
    if kind == "DYNAMIC_TYPE_DRAW":
        return "11", numeric((major.get("draw") or {}).get("id"))
    if kind == "DYNAMIC_TYPE_AV":
        return "1", numeric((major.get("archive") or {}).get("aid"))
    if kind == "DYNAMIC_TYPE_ARTICLE":
        return "12", numeric((major.get("article") or {}).get("id"))
    return "", ""


def incoming_clues(text):
    clean = normalize_text(without_mentions(text)).strip()
    brief = re.sub(r"\[[^\]\n]{1,30}\]|[\s，。！？!?~～]", "", clean)
    clues = []
    if re.search(r"(?:不要|反对|别|禁止).{0,5}(?:家访|标记|网暴)", clean):
        marker = False
    else:
        marker = bool(re.fullmatch(r"(?:来|过来|前来|过来给你)?家访(?:了|一下|打卡)?", brief)
                      or re.search(r"(?:评论区|发言|成分|视频).{0,8}(?:过来|来|进行)家访", clean))
    if marker:
        clues.append({"kind": "visit_marker", "name": "家访用语", "certainty": "explicit_marker"})
    if re.fullmatch(r"(?:标记(?:了|一下|一个|打卡)?|恍然大悟|看(?:了|完)?(?:主页|空间|动态)(?:后)?恍然大悟)", brief):
        clues.append({"kind": "weak_marker", "name": "标记 / 恍然大悟线索", "certainty": "ambiguous"})
    assessment = baseline(text)
    hits = [e for e in assessment["evidence"] if e["label"] in ATTACK_LABELS]
    if hits:
        clues.append({"kind": "incoming_attack", "name": "疑似攻击性留言", "certainty": "needs_context", "evidence": hits})
    return clues


class StopInspection(Exception):
    pass


class SpaceInspector:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or ContextFetcher()

    def inspect(self, uid, max_posts=10, comment_pages=2, max_requests=40, progress=lambda _: None, cancel=None):
        if not numeric(uid):
            raise ValueError("空间 UID 无效")
        result = empty_review(uid)
        if max_posts <= 0:
            return result
        result.update(state="unavailable", status="unknown", fetched_at=dt.datetime.now(dt.timezone.utc).isoformat())
        cov = result["coverage"] = {"feed_pages": 0, "posts_seen": 0, "posts_checked": 0, "comments_checked": 0,
                                    "reply_pages": 0, "thread_pages": 0, "request_count": 0, "skipped_other_targets": 0,
                                    "unsupported_posts": 0, "feed_exhausted": False, "truncated": False}
        result["limits"] = {"posts": max_posts, "feed_pages": 3, "comment_pages_per_post": comment_pages,
                            "thread_pages_per_root": 1, "requests": max_requests}
        seen_posts, seen_comments, seen_offsets = set(), set(), set()

        def read(path, params):
            if cancel and cancel.is_set():
                raise StopInspection("已取消空间核查")
            if cov["request_count"] >= max_requests:
                cov["truncated"] = True
                raise StopInspection("达到空间请求预算")
            cov["request_count"] += 1
            return self.fetcher.read(API + path + "?" + urlencode(params))

        def nodes_from(data, required=False):
            if required and "replies" not in data:
                raise ValueError("空间评论接口缺少 replies 字段")
            nodes = data.get("replies") or []
            if not isinstance(nodes, list) or any(not isinstance(n, dict) for n in nodes):
                raise ValueError("空间评论数据结构不可用")
            return nodes

        def mid(node):
            return numeric((node.get("member") or {}).get("mid") or node.get("mid"))

        def check_comment(node, dynamic_id, root_id, index):
            rid = numeric(node.get("rpid_str") or node.get("rpid"))
            author = mid(node)
            key = (dynamic_id, rid)
            if not rid or not author or key in seen_comments:
                return
            seen_comments.add(key)
            cov["comments_checked"] += 1
            if author == uid:
                return
            text = (node.get("content") or {}).get("message")
            if not isinstance(text, str) or not text.strip():
                return
            parent_id = numeric(node.get("parent_str") or node.get("parent"))
            is_root = rid == root_id
            parent = index.get(parent_id)
            target = "owner_or_post" if is_root else "owner" if parent and mid(parent) == uid else "other_visitor" if parent and mid(parent) != uid else "unknown"
            mentions = (node.get("content") or {}).get("members") or []
            mentioned = {mid(n) for n in mentions if isinstance(n, dict)} - {""}
            if is_root and (mentioned - {uid} or ("@" in text and not mentioned)):
                target = "other_visitor" if mentioned and uid not in mentioned else "unknown"
            if target in {"other_visitor", "unknown"}:
                cov["skipped_other_targets"] += 1
                return
            clues = incoming_clues(text)
            if clues:
                result["observations"].append({"dynamic_id": dynamic_id, "rpid": rid, "author_uid": author,
                    "text": text[:4000], "target": target, "clues": clues,
                    "parent_text": str((parent.get("content") or {}).get("message", ""))[:1000] if parent else "",
                    "source_url": f"https://t.bilibili.com/{dynamic_id}?comment_on=1&comment_root_id={root_id}#reply{rid}",
                    "authorship": "other_user", "interpretation": "他人对动态或账号的留言线索，不证明账号本人有不良行为；需核对语境。"})

        def inspect_post(item, dynamic_id):
            kind, oid = comment_ref(item)
            if not kind or not oid:
                cov["unsupported_posts"] += 1
                cov["truncated"] = True
                return
            cov["posts_checked"] += 1
            for page in range(1, comment_pages + 1):
                data = read("/x/v2/reply", {"type": kind, "oid": oid, "pn": page, "ps": 20, "sort": 2})
                cov["reply_pages"] += 1
                roots = nodes_from(data, required=True)
                if page == 1:
                    pinned = data.get("top") or {}
                    if isinstance(pinned, dict):
                        roots = [n for n in pinned.values() if isinstance(n, dict) and numeric(n.get("rpid_str") or n.get("rpid"))] + roots
                for root in roots:
                    root_id = numeric(root.get("rpid_str") or root.get("rpid"))
                    if not root_id:
                        continue
                    children = nodes_from(root)
                    count = int(root.get("rcount") or 0)
                    if count > len(children):
                        try:
                            thread = read("/x/v2/reply/reply", {"type": kind, "oid": oid, "root": root_id, "pn": 1, "ps": 20})
                            cov["thread_pages"] += 1
                            children += nodes_from(thread, required=True)
                        except (OSError, RuntimeError, ValueError, StopInspection):
                            index = {numeric(n.get("rpid_str") or n.get("rpid")): n for n in [root] + children}
                            for node in [root] + children:
                                check_comment(node, dynamic_id, root_id, index)
                            raise
                        if count > len({numeric(c.get("rpid_str") or c.get("rpid")) for c in children}):
                            cov["truncated"] = True
                    index = {numeric(n.get("rpid_str") or n.get("rpid")): n for n in [root] + children}
                    for node in [root] + children:
                        check_comment(node, dynamic_id, root_id, index)
                page_info = data.get("page") or {}
                total = page_info.get("count")
                if not roots or (isinstance(total, int) and page * 20 >= total):
                    break
                if page == comment_pages:
                    cov["truncated"] = True

        try:
            offset = ""
            for page in range(3):
                params = {"host_mid": uid}
                if offset:
                    params["offset"] = offset
                data = read("/x/polymer/web-dynamic/v1/feed/space", params)
                items = data.get("items")
                if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                    raise ValueError("动态列表结构不可用，无法判断空间留言")
                cov["feed_pages"] += 1
                for item in items:
                    dynamic_id = numeric(item.get("id_str"))
                    author = numeric(((item.get("modules") or {}).get("module_author") or {}).get("mid"))
                    if not dynamic_id or author != uid:
                        cov["unsupported_posts"] += 1
                        cov["truncated"] = True
                        continue
                    if dynamic_id in seen_posts:
                        continue
                    if len(seen_posts) >= max_posts:
                        cov["truncated"] = True
                        break
                    seen_posts.add(dynamic_id)
                    cov["posts_seen"] += 1
                    progress(f"空间留言核查：动态 {cov['posts_seen']}/{max_posts}")
                    inspect_post(item, dynamic_id)
                has_more = data.get("has_more")
                if has_more not in (True, False, 0, 1):
                    raise ValueError("动态接口缺少分页结束标记")
                if not has_more:
                    cov["feed_exhausted"] = True
                    break
                if len(seen_posts) >= max_posts or page == 2:
                    cov["truncated"] = True
                    break
                offset = str(data.get("offset") or "")
                if not offset or offset in seen_offsets:
                    raise ValueError("动态分页游标缺失或重复")
                seen_offsets.add(offset)
            result["state"] = "partial" if cov["truncated"] else "complete"
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, StopInspection) as exc:
            result["errors"].append(str(exc)[:240])
            result["state"] = "cancelled" if cancel and cancel.is_set() else "partial" if cov["reply_pages"] else "unavailable"
        result["status"] = "clues_found" if result["observations"] else "no_clues_in_sample" if result["state"] == "complete" or cov["comments_checked"] else "unknown"
        progress(f"空间留言核查：{result['state']} · {len(result['observations'])} 条线索")
        return result
