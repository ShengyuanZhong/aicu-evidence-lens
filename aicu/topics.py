"""Topic evidence and ambiguous short replies, without inferring personal beliefs."""
import re
import unicodedata
from .taxonomy import TOPICS

MENTIONS = re.compile(r"(?:回复\s*)?@[^\s:：]+\s*[:：]?\s*")
PUBLIC_INSTITUTION = re.compile(r"(?:驻[\u4e00-\u9fff]{1,5})?(?:大使馆|领事馆)|外交部|国会|议会")
AMBIGUOUS = re.compile(r"^(?:吃不上(?:米|饭)(?:而已|了)?|马圣.{0,6}上岛|头像正确|(?:xhs)?亚空间探索(?:完毕)?)$", re.I)
PUBLIC_INDICATORS = re.compile(r"人均|统计|肥胖率|寿命|失业率|生育率|贫困率|社会保障|医疗制度|粮价|米价")
COUNTRIES = re.compile(r"中国|美国|日本|韩国|英国|法国|德国|印度|俄罗斯|意大利|西班牙")


def without_mentions(text):
    return MENTIONS.sub(" ", text)


def normalize_text(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def topic_analysis(text, context="", source_context=None):
    source_context = source_context or {}
    sources = [("text", text), ("source_hint", context)]
    if source_context.get("state") in {"partial", "available"}:
        sources.extend(("source_" + key, source_context.get(key, "")) for key in ("title", "description", "area"))
        sources.extend(("source_conversation", c.get("text", "")) for c in source_context.get("conversation", [])
                       if c.get("is_root") or c.get("is_parent") or c.get("role") == "queried_author")
    evidence, seen = [], set()
    for origin, raw in sources:
        if not isinstance(raw, str) or not raw:
            continue
        clean = normalize_text(without_mentions(re.sub(r"\[[^\]\n]{1,30}\]", "", raw))).casefold()
        for key, (_, words) in TOPICS.items():
            for word in words:
                pattern = re.escape(word.casefold())
                if word.isascii():
                    pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
                if re.search(pattern, clean):
                    label = "topic_" + key
                    if (label, origin) not in seen:
                        seen.add((label, origin))
                        evidence.append({"label": label, "source": origin, "quote": word if word in raw else raw[:300],
                                         "reason": "原文话题线索" if origin == "text" else "来源讨论语境；不表示账号认同来源观点", "method": "topics-2.3"})
                    break
        indicator = PUBLIC_INDICATORS.search(clean)
        if indicator and (len(set(COUNTRIES.findall(clean))) >= 2 or re.search(r"各国|中美|日韩", clean)) and ("topic_politics", origin) not in seen:
            seen.add(("topic_politics", origin))
            evidence.append({"label": "topic_politics", "source": origin, "quote": raw[:500],
                             "reason": "跨国公共健康 / 社会指标比较，归入广义公共议题；不代表作者政治立场", "method": "topics-2.3"})
        # Mentioned public institutions identify the discussion object; arbitrary nicknames do not.
        for mention in MENTIONS.finditer(raw):
            institution = PUBLIC_INSTITUTION.search(mention.group())
            if institution and ("topic_politics", origin) not in seen:
                seen.add(("topic_politics", origin))
                evidence.append({"label": "topic_politics", "source": origin, "quote": mention.group().strip(),
                                 "reason": "点名公共机构的讨论；不推断作者立场", "method": "topics-2.3"})
    labels = list(dict.fromkeys(e["label"] for e in evidence))
    brief = re.sub(r"\[[^\]\n]{1,30}\]|[\s，。！？!?；;]", "", normalize_text(without_mentions(text)))
    candidates = []
    if AMBIGUOUS.fullmatch(brief) and "topic_politics" not in labels:
        candidates.append({"label": "topic_politics", "quote": text, "reason": "短句可能依赖公共议题语境，需查来源；昵称本身不作为话题证据"})
    return {"labels": labels, "evidence": evidence, "candidates": candidates,
            "needs_context": bool(candidates or set(labels) & {"topic_politics", "topic_military", "topic_gender", "topic_ethnicity"})}
