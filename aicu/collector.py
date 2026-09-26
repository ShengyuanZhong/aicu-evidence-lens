"""Aicu transport and response normalization."""
import datetime as dt
import itertools
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.aicu.cc/api/v3/search"
KINDS = {"comment": ("getreply", "replies", "评论"), "video": ("getvideodm", "videodmlist", "视频弹幕"), "live": ("getlivedm", "list", "直播弹幕")}

def timestamp(value):
    try:
        value = int(value)
        if value > 10**12:
            value //= 1000
        return dt.datetime.fromtimestamp(value, dt.timezone(dt.timedelta(hours=8))).isoformat() if value > 0 else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def normalize(kind, item, room=None):
    if kind == "comment":
        message, raw_time = item.get("message", ""), item.get("time")
        context = item.get("dyn") or {}
        title = context.get("title") or item.get("title") or ""
        reference = context.get("oid") or item.get("oid") or ""
    elif kind == "video":
        message, raw_time = item.get("content", ""), item.get("ctime")
        title = item.get("title") or ""
        reference = item.get("oid") or ""
    else:
        message, raw_time = item.get("text", ""), item.get("ts")
        room = room or {}
        title = room.get("roomname") or room.get("upname") or ""
        reference = room.get("roomid") or ""
    return {
        "type": kind, "text": str(message or "").strip(), "time": timestamp(raw_time),
        "context": str(title), "reference": str(reference), "raw": item,
    }


def parse_page(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError("返回内容不是 JSON 对象")
    if payload.get("code") != 0:
        raise ValueError(f"接口返回 code={payload.get('code')}: {str(payload.get('message') or payload.get('msg') or '')[:160]}")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("接口 data 字段格式不正确")
    if KINDS[kind][1] not in data:
        raise ValueError("接口缺少预期列表字段，不能视为零记录")
    listing = data[KINDS[kind][1]]
    if not isinstance(listing, list):
        raise ValueError("接口列表字段格式不正确")
    records = []
    if kind == "live":
        for group in listing:
            if not isinstance(group, dict):
                continue
            room = group.get("roominfo") or {}
            for item in group.get("danmu") or []:
                if isinstance(item, dict):
                    records.append(normalize(kind, item, room))
    else:
        records = [normalize(kind, item) for item in listing if isinstance(item, dict)]
    cursor = data.get("cursor") or {}
    total = cursor.get("all_count")
    ended = cursor.get("is_end") in (True, 1, "1") or not listing
    return records, total, ended, len(listing)


def fetch_json(url, timeout, retries):
    headers = {"User-Agent": "AicuProfile/1.0 (+local personal analysis)", "Accept": "application/json", "Referer": "https://www.aicu.cc/"}
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(f"HTTP {exc.code}：站点拒绝访问；请稍后重试或使用合法获取的本地 JSON 数据") from exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f"HTTP {exc.code}：{url}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise RuntimeError(f"请求失败：{exc}") from exc
        time.sleep(min(2 ** attempt * 2, 15))
    raise RuntimeError("重试次数已用尽")


def collect(uid, page_size, max_pages, delay, timeout, retries, progress=None, cancel=None):
    records, status = [], {}
    for kind, (endpoint, _, label) in KINDS.items():
        info = {"label": label, "pages": 0, "count": 0, "reported_total": None, "state": "complete", "error": ""}
        status[kind] = info
        previous_fingerprint = None
        for page in itertools.count(1):
            if cancel and cancel.is_set():
                info.update(state="cancelled", error="用户已停止采集")
                break
            params = {"uid": uid, "pn": page, "ps": page_size}
            if kind == "comment":
                params.update(mode=0, keyword="")
            url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
            try:
                page_records, total, ended, listed = parse_page(kind, fetch_json(url, timeout, retries))
            except (RuntimeError, ValueError) as exc:
                info.update(state="error", error=str(exc))
                break
            fingerprint = json.dumps(page_records, ensure_ascii=False, sort_keys=True)
            if page_records and fingerprint == previous_fingerprint:
                info.update(state="error", error="相邻分页返回了重复数据，已停止采集")
                break
            previous_fingerprint = fingerprint
            records.extend(page_records)
            info["pages"] += 1
            info["count"] += len(page_records)
            info["reported_total"] = total
            message = f"{label}: 第 {page} 页，新增 {len(page_records)} 条"
            if progress:
                progress(message)
            else:
                print(message, file=sys.stderr)
            if ended:
                break
            if max_pages and page >= max_pages:
                info["state"] = "page_limit"
                break
            if delay:
                time.sleep(delay)
    return records, status
