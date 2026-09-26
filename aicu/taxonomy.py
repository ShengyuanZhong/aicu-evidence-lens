"""Stable label identifiers shared by rules, models and the dashboard."""
RISK_LABELS = {
    "insult": {"name": "辱骂 / 人身攻击", "severity": 3},
    "sexual_harassment": {"name": "性骚扰 / 性化冒犯", "severity": 4},
    "sexualized": {"name": "性化表达", "severity": 2},
    "threat": {"name": "暴力威胁", "severity": 4},
    "doxxing": {"name": "人肉 / 隐私威胁", "severity": 4},
    "harassment": {"name": "组织骚扰 / 围攻", "severity": 4},
    "sarcasm": {"name": "嘲讽 / 阴阳怪气", "severity": 2},
    "gender_hostility": {"name": "性别群体攻击", "severity": 3},
    "group_hostility": {"name": "群体贬损", "severity": 3},
    "war_incitement": {"name": "战争 / 伤害鼓动", "severity": 4},
    "game_hostility": {"name": "游戏社区攻击", "severity": 3},
}
TOPICS = {
    "game": ("游戏", ["游戏", "玩家", "原神", "崩坏", "星穹铁道", "明日方舟", "王者荣耀", "英雄联盟", "LOL", "DOTA", "Minecraft", "Steam", "抽卡", "排位", "二游"]),
    "anime": ("动漫", ["动漫", "动画", "漫画", "番剧", "声优", "高达", "同人", "cosplay"]),
    "music": ("音乐", ["音乐", "歌曲", "歌手", "演唱会", "乐队", "翻唱", "唱歌", "编曲"]),
    "film": ("影视", ["电影", "电视剧", "演员", "导演", "剧情", "纪录片"]),
    "tech": ("科技数码", ["数码", "手机", "电脑", "显卡", "CPU", "GPU", "编程", "代码", "开源", "AI", "人工智能"]),
    "learning": ("知识学习", ["学习", "考试", "考研", "高考", "课程", "数学", "物理", "科普", "论文"]),
    "sport": ("运动", ["运动", "健身", "跑步", "篮球", "足球", "羽毛球", "游泳", "NBA"]),
    "life": ("美食生活", ["美食", "做饭", "咖啡", "火锅", "旅行", "旅游", "宠物", "猫咪", "狗狗"]),
    "live": ("直播 / 虚拟主播", ["直播", "主播", "VTuber", "VUP", "舰长", "开播", "切片"]),
    "politics": ("公共事务 / 涉政话题", ["政治", "政府", "政策", "选举", "总统", "议会", "政党", "国际关系"]),
}
CATALOG = {k: {**v, "kind": "risk"} for k, v in RISK_LABELS.items()}
CATALOG.update({"topic_" + k: {"name": v[0], "kind": "topic", "severity": 0} for k, v in TOPICS.items()})
STATUSES = {"suspected": "待核查", "risk": "模型判为风险", "no_risk_observed": "模型未发现风险", "unreviewed": "未作语义审核"}
