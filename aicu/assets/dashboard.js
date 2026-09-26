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
    return records.filter(r=>(filters.source==="all"||r.type===filters.source)&&(filters.status==="all"||r.assessment.status===filters.status)&&(!filters.search||r.text.toLocaleLowerCase().includes(filters.search.toLocaleLowerCase()))&&(!filters.from||(r.time&&r.time.slice(0,10)>=filters.from))&&(!filters.to||(r.time&&r.time.slice(0,10)<=filters.to))&&(!filters.topicTag||tags(r,catalog,"topic").includes(filters.topicTag))&&(!filters.riskTag||tags(r,catalog,"risk").includes(filters.riskTag)));
  }
  const api={aggregate,filterRecords,tags};
  if(typeof module!=="undefined"&&module.exports) module.exports=api;
  root.AicuDashboard=api;
  if(typeof document==="undefined") return;
  const report=JSON.parse(document.getElementById("report-data").textContent), catalog=report.catalog;
  const ordered=[...report.records].sort((a,b)=>(a.time||"9999").localeCompare(b.time||"9999")||a.id.localeCompare(b.id));
  const colorMap={};for(const kind of ["topic","risk"]){const palette=kind==="topic"?TOPIC_COLORS:RISK_COLORS;Object.keys(catalog).filter(k=>catalog[k].kind===kind).forEach((k,i)=>{colorMap[k]=palette[i%palette.length];});}
  const $=id=>document.getElementById(id);
  function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  const filters={source:"all",status:"all",search:"",from:"",to:"",topicTag:"",riskTag:""};
  let page=0,timer=null,current=[];
  $("subtitle").textContent=(report.demo?"合成演示样本 · 不对应真实账号":"UID "+report.uid)+" · "+report.records.length+" 条记录 · "+report.generated_at.slice(0,10);
  $("mode").textContent=report.mode==="offline"?"离线检索模式":"语义审核模式";
  $("notice").textContent=report.mode==="offline"?"尚未接入语义模型。带标签的记录是待核查线索，未命中记录仍是未审核；表情或情绪词不会生成友好分。来源核查会补充语境，但不会自动消除风险标签。":"模型逐条分析原文，遇到高疑点记录补充来源后复核。请结合证据阅读模型结果；审核失败与未覆盖记录保持未审核状态。";
  $("summary").textContent=report.summary||(report.summary_error?"模型评述失败："+report.summary_error:"尚未生成模型评述。逐条审核请求已导出，可配置模型后重跑已有记录。");
  for(const [k,s] of Object.entries(report.coverage||{})) $("coverage").append(node("div",(TYPES[k]||k)+"："+(s.count??0)+" 条 · "+s.state+(s.error?" · "+s.error:"")));
  $("coverage").append(node("div","来源核查："+report.context_review.attempted+" / "+report.context_review.eligible+" 条候选；已去重或排除空记录 "+report.deduplicated_or_empty+" 条。"));
  if(report.errors.length) $("coverage").append(node("div","模型或流程错误 "+report.errors.length+" 项，详情见 report.json。"));
  $("timeline").max=ordered.length;$("timeline").value=ordered.length;
  function renderEvidence(){
    const max=Math.max(1,Math.ceil(current.length/25));page=Math.min(page,max-1);$("evidence").replaceChildren();
    const sorted=[...current].sort((a,b)=>(b.time||"").localeCompare(a.time||""));
    for(const r of sorted.slice(page*25,page*25+25)){
      const a=r.assessment,card=node("article",undefined,"record");card.id=r.id;
      const head=node("div",undefined,"record-head");head.append(node("span",(TYPES[r.type]||r.type)+" · "+(r.time?r.time.replace("T"," "):"时间未知")+" · "+r.id),node("span",STATES[a.status]||a.status,"status "+a.status));card.append(head,node("p",r.text,"record-text"));
      const ts=node("div",undefined,"tags");for(const k of tags(r,catalog)){const tag=node("span",catalog[k].name,"tag "+catalog[k].kind);ts.append(tag);}card.append(ts,node("p",a.reason,"reason"));
      if(r.source_url){const link=node("a","打开 Bilibili 原始来源 ↗");link.href=r.source_url;link.target="_blank";link.rel="noopener noreferrer";card.append(link);}
      const d=node("details");d.append(node("summary","判断依据与来源上下文"));
      d.append(node("p","判断对象："+a.target+" · 方法："+a.method));for(const e of a.evidence||[])d.append(node("blockquote",e.quote),node("p",e.reason));
      const ctx=r.source_context||{};d.append(node("p","来源状态："+(ctx.state||"not_requested")+(ctx.target_found?" · 已在来源中匹配评论 ID 与账号":"")));
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
  for(const id of ["source","status","search","from","to"])$(id).addEventListener(id==="search"?"input":"change",()=>{filters[id]=$(id).value;page=0;render();});
  $("timeline").oninput=()=>{pause();page=0;render();};
  $("play").onclick=()=>{if(timer){pause();return;}if(Number($("timeline").value)>=ordered.length)$("timeline").value=0;$("play").textContent="Ⅱ 暂停";timer=setInterval(()=>{const n=Math.min(ordered.length,Number($("timeline").value)+Math.max(1,Math.ceil(ordered.length/120)));$("timeline").value=n;page=0;render();if(n>=ordered.length)pause();},400);};
  for(const kind of ["topic","risk"])$("clear-"+kind).onclick=()=>{filters[kind==="topic"?"topicTag":"riskTag"]="";page=0;render();};
  $("reset").onclick=()=>{pause();for(const k of ["source","status"])filters[k]=$(k).value="all";for(const k of ["search","from","to"])filters[k]=$(k).value="";filters.topicTag="";filters.riskTag="";$("timeline").value=ordered.length;page=0;render();};
  $("prev").onclick=()=>{page--;renderEvidence();};$("next").onclick=()=>{page++;renderEvidence();};
  $("export").onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:"application/json"}));const a=node("a");a.href=url;a.download="aicu-filtered-records.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  render();
})(typeof globalThis!=="undefined"?globalThis:this);
