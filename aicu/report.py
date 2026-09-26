"""Self-contained HTML with safe embedded JSON and no CDN dependencies."""
import html
import json
from pathlib import Path


def render_report(report):
    assets = Path(__file__).parent / "assets"
    css = (assets / "dashboard.css").read_text(encoding="utf-8")
    js = (assets / "dashboard.js").read_text(encoding="utf-8")
    data = json.dumps(report, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = "演示数据" if report.get("demo") else "UID " + report["uid"]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} · 发言观察</title><style>{css}</style></head>
<body><div class="app"><header><div class="eyebrow">AICU · EVIDENCE LENS</div><div class="title-row"><div><h1>公开发言观察</h1><p id="subtitle"></p></div><span id="mode" class="badge"></span></div><p class="intro">从标签分布回到原文，看见表达与上下文。每一条结论都可以追溯。</p></header>
<main><section id="notice" class="notice"></section><section class="metrics" id="metrics"></section>
<section class="panel controls"><div class="section-heading"><h2>探索样本</h2><button id="reset" class="quiet">重置筛选</button></div><div class="filter-grid">
<label>发言来源<select id="source"><option value="all">全部来源</option><option value="comment">评论</option><option value="video">视频弹幕</option><option value="live">直播弹幕</option></select></label>
<label>审核状态<select id="status"><option value="all">全部状态</option><option value="suspected">待核查</option><option value="risk">模型判为风险</option><option value="no_risk_observed">模型未发现风险</option><option value="unreviewed">未作语义审核</option></select></label>
<label>搜索原文<input id="search" type="search" placeholder="输入关键词"></label>
<label>起始日期<input id="from" type="date"></label><label>结束日期<input id="to" type="date"></label></div>
<div class="timeline"><button id="play" aria-label="按时间播放">▶ 播放</button><input type="range" id="timeline" min="0" value="0" aria-label="按时间累计显示记录"><span id="time-label"></span></div><p class="small">播放按时间逐条累积；无时间记录放在末尾。筛选同时更新计数、面积和证据。</p></section>
<section class="panel"><div class="section-heading"><div><h2>内容分区</h2><p class="small">仅统计游戏、动漫、音乐等话题标签。每条发言可属于多个分区；扇区面积为该分区计数占全部分区标签计数的比例。</p></div><button id="clear-topic" class="quiet" hidden>清除分区筛选</button></div><div class="distribution"><div class="ring-wrap"><div id="ring-topic" class="ring" role="img" aria-label="内容分区计数占比"><div class="ring-center"><strong id="assignments-topic">0</strong><span>分区标签</span></div></div><p id="selected-topic" class="small"></p></div><div id="legend-topic" class="legend"></div></div><p id="empty-topic" class="empty" hidden>当前范围没有内容分区标签。</p></section>
<section class="panel"><div class="section-heading"><div><h2>负面表达筛选</h2><p class="small">仅统计辱骂、性化冒犯、群体攻击等风险标签。扇区面积为该类别计数占全部风险标签计数的比例；离线命中仍需核查。</p></div><button id="clear-risk" class="quiet" hidden>清除风险筛选</button></div><div class="distribution"><div class="ring-wrap"><div id="ring-risk" class="ring" role="img" aria-label="负面表达计数占比"><div class="ring-center"><strong id="assignments-risk">0</strong><span>风险标签</span></div></div><p id="selected-risk" class="small"></p></div><div id="legend-risk" class="legend"></div></div><p id="empty-risk" class="empty" hidden>当前范围没有风险标签；未审核记录不能据此视为安全。</p></section>
<section class="panel"><div class="section-heading"><h2>逐条证据</h2><button id="export" class="quiet">导出当前记录</button></div><p id="evidence-meta" class="small"></p><div id="evidence"></div><div class="pagination"><button id="prev">上一页</button><span id="page-info"></span><button id="next">下一页</button></div></section>
<section class="panel"><h2>账号发言评述</h2><p id="summary" class="summary"></p></section><section class="panel"><h2>数据与审核覆盖</h2><div id="coverage"></div><p class="small">离线规则用于找候选；模型输出是待核查的分析。缺失、未审核与未发现风险分别展示，不折算为“友好分”。涉政话题不计为风险，报告不推断心理或敏感身份。</p></section>
</main><footer>本地报告 · 点击原始来源时才访问 Bilibili · 无外部图表依赖</footer></div><script type="application/json" id="report-data">{data}</script><script>{js}</script></body></html>'''
