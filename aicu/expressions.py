"""Phrase-level recall for euphemisms; keep original text and explain ambiguity.

Aliases are matched only in bounded constructions, never globally substituted.
Context can resolve a weak cue, but cannot create a quote the author never wrote.
"""
import re
from .topics import normalize_text, without_mentions

ADDRESS = r"(?:姐姐们?|姐姐|姐|学姐|御姐|妹妹|美女|主播|妈妈|妈咪|哥哥|哥哥们|哥)"
REQUEST = r"(?:我)?(?:想|要|可不可以|可以|能不能|能否|好想|想要)"
TAIL = r"[呀啊吧吗嘛呢啦哇哦喔辣了~～!！?？。.,，\s]*"
SEX_ALIASES = r"(?:打飞机|哒飞机|哒菲|打飞|打[个只次]?✈|打[个只次]?🛩|稻罐|道馆|导管|稻管|稻贯|倒灌|導管)"
MILK = r"(?:奶奶|奶|乃乃|奈奈|木乳|母乳|氖|赖)"
LITERAL_CONTEXT = {
    "milk": re.compile(r"婴儿|婴幼儿|宝宝|新生儿|哺乳|母乳喂养|喂奶|奶粉|牛奶|羊奶|奶茶|早餐|奶制品|乳制品|冲奶"),
    "vehicle": re.compile(r"卡车|货车|半挂|大巴|客车|驾照|驾驶模拟|模拟驾驶|货运|跑运输|卡车司机|货车司机|换挡|方向盘"),
    "shoot": re.compile(r"干燥|晾干|烘干|干活|做家务|这个工作|这份工作|这活|摄影后期|照片后期|修图教程"),
    "masturbation": re.compile(r"宝可梦.*道馆|道馆.*(?:挑战|徽章|馆主)|导管.*(?:护理|置入|手术)|飞机大战|打飞机游戏|飞机模型|折纸飞机|玩具飞机"),
}


def clean_expression(text):
    text = re.sub(r"\[(?:飞机|小飞机)\]", "✈", text)
    text = re.sub(r"\[[^\]\n]{1,30}\]", "", text)
    return normalize_text(without_mentions(text)).replace("\ufe0f", "").replace("\ufe0e", "")


def context_texts(context="", source_context=None, nearby=None):
    result = [("source_hint", context)] if isinstance(context, str) and context else []
    ctx = source_context or {}
    if ctx.get("state") in {"partial", "available"} and not ctx.get("historical_unavailable"):
        result.extend(("source_" + k, ctx.get(k, "")) for k in ("title", "description"))
        result.extend(("source_conversation", c.get("text", "")) for c in ctx.get("conversation", [])
                      if (c.get("is_parent") or c.get("is_root")) and c.get("role") != "queried_author")
    result.extend(("nearby_author:" + r["id"], r["text"]) for r in nearby or [])
    return [(origin, text) for origin, text in result if isinstance(text, str) and text.strip()]


def sexual_expressions(text, context="", source_context=None, nearby=None):
    evidence, candidates, resolutions = [], [], []
    sources = context_texts(context, source_context, nearby)
    clean = clean_expression(text)

    def add(rule, quote, reason, directed=False, literal=None, ambiguous=False):
        if any(e.get("rule") == rule and e["quote"] in quote for e in evidence):
            return
        # Quotation/objection scopes are kept separate from direct solicitations.
        normalized = clean_expression(quote)
        if re.search(r"(?:不要|别|不许|禁止|反对|不能).{0,12}(?:说|发|刷|问|喊|要求)", normalized) or re.search(r"[“\"‘].+[”\"’].{0,10}(?:不对|不合适|不应该|骚扰|举报|什么意思|含义)", normalized) or re.search(r"(?:有人|他|她)(?:说|发|留言).{0,5}[“\"‘]", normalized):
            return
        if literal:
            literal_sources = [(o, t) for o, t in [("text", normalized)] + sources if not o.startswith("nearby_author:") and LITERAL_CONTEXT[literal].search(t)]
            if literal_sources:
                origin, value = literal_sources[0]
                resolutions.append({"rule": rule, "quote": quote, "source": origin, "context_quote": value[:500],
                                    "reason": "来源有明确字面用法，弱隐语不自动标为性化；仍可由模型复核。"})
                return
        entry = {"label": "sexualized", "quote": quote, "rule": rule, "reason": reason}
        if ambiguous:
            # Only an independently specific neighbouring phrase supplies this signal.
            supporting = [(o, t) for o, t in sources if re.search(r"打飞机|哒菲|稻罐|木乳|乃乃|[🔪].{0,6}[🖊]|性暗示|性骚扰", clean_expression(t))]
            if not supporting:
                candidates.append(entry)
                return
            origin, value = supporting[0]
            entry.update(context_source=origin, context_quote=value[:500])
            entry["reason"] += " 同一来源或邻近本人发言提供性化线索，仍需语义核查。"
        evidence.append(entry)
        if directed:
            evidence.append({**entry, "label": "sexual_harassment", "reason": reason + " 发言指向他人，列为性化冒犯候选；对象、引用关系及互动语境仍需核查。"})

    # Explicit paired symbols retain their meaning even with positive emoji.
    clauses = re.split(r"[，,。！!？?；;\n]", text)
    if len(clauses) > 1 and len(text) <= 100 and re.search(ADDRESS, clean):
        clauses.append(text)
    for clause in clauses:
        c = clean_expression(clause).strip()
        if not c:
            continue
        if re.search(r"(?:帮我|给我|替我|为我)(?:打|哒)[个只次]?\s*(?:✈|🛩|飞机)", c):
            add("sexual_solicitation_plane", clause.strip(), "请求他人“打飞机”或使用飞机表情替代，存在性请求线索。", True, "masturbation")
        elif re.search(ADDRESS + r".{0,10}" + REQUEST + r".{0,2}" + SEX_ALIASES + TAIL + r"$", c) or re.search(r"(?:我想|我要|想要)" + SEX_ALIASES + TAIL + r"$", c):
            add("masturbation_alias", clause.strip(), "欲望句式中的飞机 / 稻罐 / 哒菲等替代词，疑似自慰或性暗示。", bool(re.search(ADDRESS, c)), "masturbation")
        elif re.fullmatch(ADDRESS + r".{0,6}(?:想|要|可不可以|可以|能不能|帮我)(?:打|哒|稻)" + TAIL, c):
            add("addressed_ellipsis", clause.strip(), "称呼对象后使用省略宾语的“想打 / 哒”等句式，存在隐晦性化线索；不能仅凭“打”字判断。", True, "masturbation")
        if re.search(r"(?:🔪|稻|捣)\s*(?:你|她|姐姐|妈妈)(?:的)?\s*🖊|(?:我想|我要|可以|能不能)(?:🔪|稻|捣)\s*🖊|🖊\s*(?:给|能|可以|可不可以)\s*🔪", c):
            add("paired_sexual_symbols", clause.strip(), "刀 / 稻与笔表情在针对对象的组合句式中疑似替代性行为和性部位词。", True)
        if re.search(ADDRESS + r".{0,10}(?:想|要|可以|能不能|让我|怎样才能).{0,4}(?:喝|吃|饮|吸)" + MILK + TAIL + r"$", c) or re.fullmatch(r"(?:上舰|总督).{0,5}(?:可以|能)(?:喝|吃)奶" + TAIL, c):
            add("addressed_milk", clause.strip(), "对他人索取“奶 / 乃乃 / 木乳”等，疑似对身体的性化请求；需排除喂养或食品语境。", True, "milk")
        if re.search(r"(?:拍|录)完(?:了)?(?:可不可以|可以|能不能|能)(?:干|艹|操)" + TAIL + r"$", c):
            add("after_shoot_request", clause.strip(), "拍摄后使用没有工作宾语的“可以干吗”等句式，疑似性请求。", True, "shoot")
        if re.search(r"(?:大车.{0,5}开.{0,5}爽|(?:想|要)开大车|干起来.{0,5}(?:爽|到底))", c):
            add("vehicle_or_action_metaphor", clause.strip(), "“开大车 / 干起来”与欲望或快感搭配，疑似性化比喻；需核对对象，不能推断对象年龄。", False, "vehicle" if "车" in c else "shoot")
        if re.search(ADDRESS + r".{0,5}(?:我想骑你|我进你里面|你里面.{0,3}(?:烫|紧)|我进的你爽|你紧吗|我想进去.{0,8}紧不紧|.{0,6}稻你.{0,8}出生点)", c):
            add("targeted_body_innuendo", clause.strip(), "直接对他人使用进入身体、骑或身体松紧等性化句式。", True)
        if re.search(r"(?:我想|我要|我可不可以)(?:睡|上|操|艹|干)你(?!的(?:工作|活|事情))", c):
            add("direct_sexual_request", clause.strip(), "对他人提出直接性化要求。", True)
        if re.search(ADDRESS + r".{0,6}(?:变成了我的形状|你是什么杯的|你什么罩杯|我.{0,3}态哒了|我进不去.{0,5}态哒)", c):
            add("body_objectification", clause.strip(), "把他人身体作为性对象或使用隐写身体词的表达。", True)
        if re.fullmatch(r"(?:我是人.{0,5})?(?:让我爽的方法是|我想|我要)(?:🦌|撸)" + TAIL, c):
            add("deer_masturbation", clause.strip(), "鹿表情 / 撸与快感或欲望组合，疑似自慰暗示。")

    # Weak fragments are visible as pending meanings, not silently counted as risks.
    pending_patterns = [
        ("milk_fragment", r"(?:(?:我(?:饿了|渴了))?[，,]?\s*)?(?:我)?(?:想|要)(?:喝|吃)奶" + TAIL, "milk", "喝奶短句存在食品与性隐语两种解释，需要同一对话的证据。"),
        ("help_fragment", r"(?:你)?(?:可不可以|能不能|可以)?(?:帮我|给我|替我)(?:打|哒)" + TAIL, "masturbation", "省略宾语的求助短句，需确认是在说游戏、工作还是性隐语。"),
        ("release_fragment", ADDRESS + r".{0,4}(?:我出来了|我好爽|我忍不住了|我好胀|我爽死了|我想进去|我想听爽的)" + TAIL, None, "快感 / 出来等省略表达可能有多种含义，需要邻近对话确认。"),
    ]
    if not evidence:
        for rule, pattern, literal, reason in pending_patterns:
            if re.fullmatch(pattern, clean.strip()):
                add(rule, text, reason, bool(re.search(ADDRESS, clean)), literal, ambiguous=True)
    return {"evidence": evidence, "candidates": candidates, "resolutions": resolutions}
