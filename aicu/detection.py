"""Conservative offline recall layer; there is deliberately no positivity score."""
import re
from .taxonomy import RISK_LABELS
from .topics import normalize_text, without_mentions, topic_analysis

RULE_VERSION = "rules-2.3"
RULES = {
    "insult": [r"傻[\s*·._-]*[逼b比杯]", r"煞[\s*·._-]*笔|傻波一|沙币", r"脑残|弱智|废物|狗东西", r"你.{0,5}垃圾", r"滚[蛋开]|死[妈全]家"],
    "sexual_harassment": [r"(?:妈妈|母亲|你妈|她妈).{0,8}(?:处女|第一次|身体).{0,10}(?:我|占有)", r"(?:想|要|让).*?(?:睡你|上你|操你|摸你)", r"给我看.{0,5}(?:胸|内裤|身体)", r"你的.{0,5}(?:处女|第一次).{0,8}(?:我|要了)"],
    "sexualized": [r"处女(?!座|作|航).{0,10}(?:我的|属于我|是我)", r"(?:想睡|想上)[你他她]", r"(?:胸|屁股).{0,3}(?:大|翘|摸)", r"约炮|精液|肉便器"],
    "threat": [r"弄死你|杀了你|打死你", r"找到你.{0,8}(?:打|杀)"],
    "doxxing": [r"(?:开盒|人肉)[你他她]", r"把.{0,8}地址.{0,5}(?:发|贴|公布)"],
    "harassment": [r"(?:大家|一起|都).{0,8}(?:去冲|去骂|网暴|私信轰炸)", r"去.{0,8}评论区.{0,5}(?:冲|骂)"],
    "sarcasm": [r"呵呵|急了急了|典中典|不会吧不会吧", r"你可真是个天才|懂的都懂", r"孝子.{0,4}(?:急|破防)"],
    "gender_hostility": [r"(?:男人|男的|女人|女的)都.{0,12}(?:蠢|垃圾|恶心|下贱|该死)", r"(?:普信男|蝈男|女拳|小仙女).{0,8}(?:滚|垃圾|恶心|去死)"],
    "group_hostility": [r"(?:外地人|穷人|老人|小孩)都.{0,12}(?:垃圾|该死|恶心|低等)"],
    "ethnic_discrimination": [r"棒子国|高丽棒子", r"(?:韩国人|日本人|蒙古人|维吾尔人|汉族人|黑人|白人)(?:都是|全是|天生).{0,8}(?:低等|劣等|垃圾|该死)"],
    "war_incitement": [r"(?:应该|支持|必须|赶紧).{0,10}(?:开战|轰炸|屠杀|核平)", r"杀光.{0,12}(?:平民|他们|她们)", r"把.{0,10}(?:城市|国家|平民).{0,8}(?:炸平|夷平)"],
    "game_hostility": [r"(?:原批|农批|粥批|米孝子|库孝子).{0,12}(?:滚|恶心|垃圾|脑残|去死)", r"(?:原神|王者|明日方舟|崩坏).{0,5}玩家都.{0,10}(?:垃圾|脑残|恶心)"],
}
COMPILED = {k: [re.compile(p, re.I) for p in patterns] for k, patterns in RULES.items()}


def topic_tags(text, context=""):
    return topic_analysis(text, context)["labels"]


def baseline(text):
    evidence = []
    quoted_report = bool(re.search(r"[“\"].+[”\"].{0,15}(?:不对|不合适|不能|不应该|反对)", text))
    for clause in re.split(r"[，,。！!？?；;\n]", text):
        clean = normalize_text(without_mentions(re.sub(r"\[[^\]\n]{1,30}\]", "", clause)))
        for key, patterns in COMPILED.items():
            hit = next((m for p in patterns if (m := p.search(clean))), None)
            if not hit:
                continue
            prefix = clean[max(0, hit.start() - 24):hit.start()]
            # Scope negation to this expression, never discard the entire comment.
            if re.search(r"(?:不要|不能|不许|禁止|反对|抵制|别)(?:再|去|说|叫|骂|称|支持|鼓动|别人|他|她|你|人|是|为|这种|言论|行为|[‘'“\"]|\s){0,10}$", prefix):
                continue
            if re.search(r"(?:不要|不能|不应该|别).{0,8}(?:称呼|叫作|骂|使用|用|叫|说).{0,8}$", prefix):
                continue
            evidence.append({"label": key, "quote": clause.strip(), "reason": "存在针对性或冒犯性表达线索；需结合对象、引用关系和语境核查。" if not quoted_report else "存在引用 / 反对语境，不能直接归因于作者。"})
    brief = re.sub(r"\[[^\]\n]{1,30}\]|[\s，。！？!?]", "", normalize_text(without_mentions(text)))
    if re.fullmatch(r"(?:(?:你|你个|你这|这人|这只|这条|真是个))?也够", brief):
        evidence.append({"label": "insult", "quote": text, "reason": "独立评价位置的“也够”疑似“野狗”的谐音替代；需要原评论对象与上下文确认。", "normalized_hint": "也够 → 野狗（疑似）"})
    if re.fullmatch(r"(?:(?:你|你个|这人|楼上)(?:就是|是个|是)?)?s[\s._*-]*b", brief, re.I):
        evidence.append({"label": "insult", "quote": text, "reason": "独立或指向他人的 SB 缩写，疑似辱骂；需结合语境核查。"})
    if re.fullmatch(r"(?:(?:你|你个|这人|楼上)(?:就是|是个|是)?)?(?:野狗|畜生|滚)", brief) or re.fullmatch(r"(?:你|你个|这人|楼上)(?:就是|是个|是)?(?:出生|初生)", brief):
        evidence.append({"label": "insult", "quote": text, "reason": "独立评价或针对对象的贬损 / 谐音用语线索；需排除字面与引用语境。"})
    labels = list(dict.fromkeys(e["label"] for e in evidence))
    if quoted_report:
        # Retain the evidence but put the interpretation explicitly in dispute.
        priority = 2 if labels else 0
    else:
        priority = max((RISK_LABELS[k]["severity"] for k in labels), default=0)
    return {"status": "suspected" if labels else "unreviewed", "risk_labels": labels,
            "priority": priority, "needs_context": bool(labels), "target": "待确认",
            "evidence": evidence, "reason": "离线规则候选，尚未完成语义审核。" if labels else "未命中离线规则；不等于无风险。",
            "method": RULE_VERSION, "model_checked": False}
