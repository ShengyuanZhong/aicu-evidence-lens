/* Shared pure aggregation functions also run in Node regression tests. */
(function (root) {
  "use strict";
  const TYPES = {comment:"评论",video:"视频弹幕",live:"直播弹幕"};
  const STATES = {suspected:"待核查",risk:"模型判为风险",no_risk_observed:"模型未发现风险",unreviewed:"未作语义审核"};
  const TOPIC_COLORS = ["#3775c5","#2b9c9a","#7b70bd","#88a53b","#507898","#72a5d8","#a18fd0","#6bb8a4"];
  const RISK_COLORS = ["#c55357","#df8654","#b75a82","#ba724e","#a44f65","#d5a047","#985c78","#c97968"];
  function tags(record, catalog, scope="all") {return [...new Set([...(record.topic_labels||[]),...(record.assessment.risk_labels||[])])].filter(k=>catalog[k] && (scope==="all"||catalog[k].kind===scope));}
  function aggregate(records, catalog, scope="all") {
    const counts = new Map();
    for (const r of records) for (const k of tags(r,catalog,scope)) counts.set(k,(counts.get(k)||0)+1);
    const total=[...counts.values()].reduce((a,b)=>a+b,0);
    return {total,labels:[...counts].map(([id,count])=>({id,count,share:total?count/total:0,coverage:records.length?count/records.length:0})).sort((a,b)=>b.count-a.count||a.id.localeCompare(b.id))};
  }
  function filterRecords(records, filters, catalog) {
    return records.filter(r=>(filters.source==="all"||r.type===filters.source)&&(filters.status==="all"||r.assessment.status===filters.status||(filters.status==="meaning_pending"&&(r.assessment.context_candidates||[]).length))&&(!filters.search||r.text.toLocaleLowerCase().includes(filters.search.toLocaleLowerCase()))&&(!filters.from||(r.time&&r.time.slice(0,10)>=filters.from))&&(!filters.to||(r.time&&r.time.slice(0,10)<=filters.to))&&(!filters.topicTag||tags(r,catalog,"topic").includes(filters.topicTag))&&(!filters.riskTag||tags(r,catalog,"risk").includes(filters.riskTag))&&(!filters.topicState||filters.topicState==="all"||(filters.topicState==="pending"&&(r.topic_candidates||[]).length)||(filters.topicState==="labeled"&&(r.topic_labels||[]).length)||(filters.topicState==="unlabeled"&&!(r.topic_labels||[]).length)));
  }
  function spaceStatus(review={}) {
    if(review.status==="clues_found")return "发现留言线索 · 需核对";
    if(review.state==="unavailable"||review.status==="unknown")return "无法确认";
    if(review.status==="no_clues_in_sample")return "已检查样本内未发现线索";
    return "未检查";
  }
  const api={aggregate,filterRecords,tags,spaceStatus};
  if(typeof module!=="undefined"&&module.exports) module.exports=api;
  root.AicuDashboard=api;
  if(typeof document==="undefined") return;
  const report=JSON.parse(document.getElementById("report-data").textContent), catalog=report.catalog;
  const ordered=[...report.records].sort((a,b)=>(a.time||"9999").localeCompare(b.time||"9999")||a.id.localeCompare(b.id));
  const colorMap={};for(const kind of ["topic","risk"]){const palette=kind==="topic"?TOPIC_COLORS:RISK_COLORS;Object.keys(catalog).filter(k=>catalog[k].kind===kind).forEach((k,i)=>{colorMap[k]=palette[i%palette.length];});}
  const $=id=>document.getElementById(id);
  function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  const filters={source:"all",status:"all",search:"",from:"",to:"",topicTag:"",riskTag:"",topicState:"all"};
  let page=0,timer=null,current=[];
  $("subtitle").textContent=(report.demo?"合成演示样本 · 不对应真实账号":"UID "+report.uid)+" · "+report.records.length+" 条记录 · "+report.generated_at.slice(0,10);
  $("mode").textContent=report.mode==="offline"?"离线检索模式":"语义审核模式";
  $("notice").textContent=report.mode==="offline"?"尚未接入语义模型。带标签的记录是待核查线索，未命中记录仍是未审核；表情或情绪词不会生成友好分。来源可帮助重新判断弱隐语，变更保留依据；含义待确认的短句不计入风险圆环。":"模型逐条分析原文，遇到高疑点记录补充来源后复核。请结合证据阅读模型结果；审核失败与未覆盖记录保持未审核状态。";
  $("summary").textContent=report.summary||(report.summary_error?"模型评述失败："+report.summary_error:"尚未生成模型评述。逐条审核请求已导出，可配置模型后重跑已有记录。");
  for(const [k,s] of Object.entries(report.coverage||{})) $("coverage").append(node("div",(TYPES[k]||k)+"："+(s.count??0)+" 条 · "+s.state+(s.error?" · "+s.error:"")));
  $("coverage").append(node("div","来源核查："+report.context_review.attempted+" / "+report.context_review.eligible+" 条候选；已去重或排除空记录 "+report.deduplicated_or_empty+" 条。"));
  if(report.errors.length) $("coverage").append(node("div","模型或流程错误 "+report.errors.length+" 项，详情见 report.json。"));
  $("timeline").max=ordered.length;$("timeline").value=ordered.length;
  const origins={text:"账号原文",source_hint:"采集来源提示",source_title:"来源标题",source_description:"来源简介",source_area:"来源分区",source_conversation:"评论上下文（可能为其他作者）"};
  const space=report.space_review||{}, observations=space.observations||[], sc=space.coverage||{};
  $("space-status").textContent=spaceStatus(space);
  $("space-meta").textContent="已检查 "+(sc.posts_checked||0)+" 条动态 / "+(sc.comments_checked||0)+" 条留言 · 找到 "+observations.length+" 条线索 · "+({complete:"本次范围检查完成",partial:"部分覆盖",unavailable:"访问不可用",cancelled:"已取消",not_requested:"未启用检查"}[space.state]||"未检查");
  $("space-caution").textContent="这是有限的公开样本，可能遗漏旧动态、楼中楼、删除或登录后可见的留言。‘标记’‘恍然大悟’也可能有其他含义；来源链接和回复对象需要人工核对。";
  for(const error of space.errors||[])$("space-errors").append(node("p",error));
  if(/^[1-9][0-9]{0,19}$/.test(report.uid))$("space-link").href="https://space.bilibili.com/"+report.uid+"/dynamic";else $("space-link").hidden=true;
  let spacePage=0;
  function renderSpace(){
    $("space-evidence").replaceChildren();
    const max=Math.max(1,Math.ceil(observations.length/15));spacePage=Math.max(0,Math.min(spacePage,max-1));
    for(const o of observations.slice(spacePage*15,spacePage*15+15)){
      const card=node("article",undefined,"record");
      card.append(node("p","其他用户留言 · "+(o.clues||[]).map(c=>c.name).join(" / "),"reason"),node("p",o.text,"record-text"));
      card.append(node("p",o.target==="owner"?"回复对象：已匹配查询账号的评论":"留言位置：查询账号发布的动态，具体指向需核查","small"));
      if(o.parent_text)card.append(node("blockquote","所回复内容："+o.parent_text));
      card.append(node("p",o.interpretation,"small"));
      if(/^https:\/\/t\.bilibili\.com\/[0-9]+\?comment_on=1&comment_root_id=[0-9]+#reply[0-9]+$/.test(o.source_url||"")){
        const link=node("a","核查原始留言 ↗");link.href=o.source_url;link.target="_blank";link.rel="noopener noreferrer";card.append(link);
      }
      $("space-evidence").append(card);
    }
    if(!observations.length)$("space-evidence").append(node("p",space.status==="no_clues_in_sample"?"本次已读取的样本内没有命中线索，不能据此断言从未被家访。":"尚无可用于判断的留言证据。","empty"));
    $("space-page").textContent=(spacePage+1)+" / "+max;
    $("space-prev").disabled=spacePage===0;$("space-next").disabled=spacePage===max-1;
  }
  $("space-prev").onclick=()=>{spacePage--;renderSpace();};$("space-next").onclick=()=>{spacePage++;renderSpace();};renderSpace();
  function renderEvidence(){
    const max=Math.max(1,Math.ceil(current.length/25));page=Math.min(page,max-1);$("evidence").replaceChildren();
    const sorted=[...current].sort((a,b)=>(b.time||"").localeCompare(a.time||""));
    for(const r of sorted.slice(page*25,page*25+25)){
      const a=r.assessment,card=node("article",undefined,"record");card.id=r.id;
      const head=node("div",undefined,"record-head");head.append(node("span",(TYPES[r.type]||r.type)+" · "+(r.time?r.time.replace("T"," "):"时间未知")+" · "+r.id),node("span",STATES[a.status]||a.status,"status "+a.status));card.append(head,node("p",r.text,"record-text"));
      const ts=node("div",undefined,"tags");for(const k of tags(r,catalog)){const tag=node("span",catalog[k].name,"tag "+catalog[k].kind);ts.append(tag);}card.append(ts,node("p",a.reason,"reason"));
      for(const e of r.topic_candidates||[])card.append(node("p","待确认话题："+(catalog[e.label]?.name||e.label)+" · "+e.reason,"pending-topic"));
      for(const e of a.context_candidates||[])card.append(node("p","含义待确认："+e.reason,"pending-topic"));
      if(r.source_url){const link=node("a",r.source_url.startsWith("https://api.bilibili.com/")?"查看 Bilibili 原始评论数据 ↗":"打开 Bilibili 原始来源 ↗");link.href=r.source_url;link.target="_blank";link.rel="noopener noreferrer";card.append(link);}
      const d=node("details");d.append(node("summary","判断依据与来源上下文"));
      d.append(node("p","判断对象："+a.target+" · 方法："+a.method));for(const e of a.evidence||[]){d.append(node("blockquote",e.quote),node("p",e.reason));if(e.context_quote)d.append(node("p","辅助语境 · "+e.context_source),node("blockquote",e.context_quote));}
      for(const e of a.literal_resolutions||[])d.append(node("p",e.reason),node("blockquote",e.context_quote));
      for(const e of r.topic_evidence||[])d.append(node("p","话题依据 · "+(catalog[e.label]?.name||e.label)+" · "+(origins[e.source]||e.source)),node("blockquote",e.quote),node("p",e.reason,"small"));
      const ctx=r.source_context||{};d.append(node("p","来源状态："+(ctx.state||"not_requested")+(ctx.target_found?" · 已在来源中匹配评论 ID 与账号":"")));
      if(ctx.reason)d.append(node("p",ctx.reason));
      for(const n of r.nearby_author||[])d.append(node("p","同一房间邻近本人发言 · "+n.time+" · "+n.id),node("blockquote",n.text));
      if(ctx.title)d.append(node("p","标题："+ctx.title));if(ctx.description)d.append(node("p","简介："+ctx.description));
      for(const c of ctx.conversation||[])d.append(node("blockquote",(c.role==="queried_author"?"查询账号：":"其他作者 / 未确认归属：")+c.text));
      for(const err of [...(ctx.errors||[]),...(r.errors||[])])d.append(node("p",err));
      if(r.audit.length)d.append(node("pre",JSON.stringify(r.audit,null,2)));card.append(d);$("evidence").append(card);
    }
    if(!current.length)$("evidence").append(node("p","当前筛选没有记录。","empty"));
    $("page-info").textContent=(page+1)+" / "+max;$("prev").disabled=page===0;$("next").disabled=page===max-1;
  }
  function renderRing(kind){
    const result=aggregate(current,catalog,kind),active=kind==="topic"?"topicTag":"riskTag";
    $("assignments-"+kind).textContent=result.total;
    let pos=0;
    const segments=result.labels.map(x=>{const from=pos;pos+=x.share*360;return colorMap[x.id]+" "+from+"deg "+pos+"deg";});
    $("ring-"+kind).style.background=segments.length?"conic-gradient("+segments.join(",")+")":"#e8edf3";
    $("ring-"+kind).setAttribute("aria-label",result.labels.map(x=>catalog[x.id].name+" "+x.count+" 次 "+(x.share*100).toFixed(1)+"%").join("；")||"没有标签");
    $("legend-"+kind).replaceChildren();
    for(const x of result.labels){
      const b=node("button",undefined,"legend-row"+(filters[active]===x.id?" selected":""));
      b.title="占本图标签 "+(x.share*100).toFixed(1)+"%；覆盖当前发言 "+(x.coverage*100).toFixed(1)+"%";
      const sw=node("span",undefined,"swatch");sw.style.background=colorMap[x.id];
      const name=node("span",undefined,"legend-label");name.append(node("span",catalog[x.id].name));
      const track=node("span",undefined,"bar-track"),fill=node("span",undefined,"bar-fill");fill.style.display="block";fill.style.background=colorMap[x.id];fill.style.width=(x.share*100)+"%";track.append(fill);name.append(track);
      b.append(sw,name,node("span",String(x.count),"legend-count"),node("span",(x.share*100).toFixed(1)+"%","legend-percent"));
      b.onclick=()=>{filters[active]=filters[active]===x.id?"":x.id;page=0;render();};$("legend-"+kind).append(b);
    }
    $("empty-"+kind).hidden=result.total>0;
    $("clear-"+kind).hidden=!filters[active];
    $("selected-"+kind).textContent=filters[active]?"正在查看："+catalog[filters[active]].name:"点击标签可联动查看证据";
  }
  function render(){
    const cutoff=Number($("timeline").value);current=filterRecords(ordered.slice(0,cutoff),filters,catalog);
    $("metrics").replaceChildren();for(const [label,value] of [["当前发言",current.length],["待核查",current.filter(r=>r.assessment.status==="suspected").length],["语义审核覆盖",current.filter(r=>r.assessment.model_checked).length],["可用来源上下文",current.filter(r=>["partial","available"].includes(r.source_context.state)).length]]){const m=node("div",undefined,"metric");m.append(node("span",label),node("strong",String(value)));$("metrics").append(m);}
    $("time-label").textContent=cutoff+" / "+ordered.length+" · "+(cutoff?(ordered[cutoff-1].time||"时间未知").slice(0,10):"尚未开始");
    renderRing("topic");renderRing("risk");
    $("evidence-meta").textContent=current.length+" 条记录 · 每页 25 条 · 同一发言可含多个标签";renderEvidence();
  }
  function pause(){if(timer)clearInterval(timer);timer=null;$("play").textContent="▶ 播放";}
  for(const id of ["source","status","search","from","to","topicState"])$(id).addEventListener(id==="search"?"input":"change",()=>{filters[id]=$(id).value;page=0;render();});
  $("timeline").oninput=()=>{pause();page=0;render();};
  $("play").onclick=()=>{if(timer){pause();return;}if(Number($("timeline").value)>=ordered.length)$("timeline").value=0;$("play").textContent="Ⅱ 暂停";timer=setInterval(()=>{const n=Math.min(ordered.length,Number($("timeline").value)+Math.max(1,Math.ceil(ordered.length/120)));$("timeline").value=n;page=0;render();if(n>=ordered.length)pause();},400);};
  for(const kind of ["topic","risk"])$("clear-"+kind).onclick=()=>{filters[kind==="topic"?"topicTag":"riskTag"]="";page=0;render();};
  $("reset").onclick=()=>{pause();for(const k of ["source","status","topicState"])filters[k]=$(k).value="all";for(const k of ["search","from","to"])filters[k]=$(k).value="";filters.topicTag="";filters.riskTag="";$("timeline").value=ordered.length;page=0;render();};
  $("prev").onclick=()=>{page--;renderEvidence();};$("next").onclick=()=>{page++;renderEvidence();};
  $("export").onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:"application/json"}));const a=node("a");a.href=url;a.download="aicu-filtered-records.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  render();
})(typeof globalThis!=="undefined"?globalThis:this);
