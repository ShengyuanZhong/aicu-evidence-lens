const assert=require('node:assert/strict');
const {aggregate,filterRecords,spaceStatus}=require('../aicu/assets/dashboard.js');
const catalog={insult:{kind:'risk'},sexual:{kind:'risk'},game:{kind:'topic'}};
const records=[{type:'comment',time:'2026-01-01',text:'first',topic_labels:['game'],assessment:{risk_labels:['insult','insult'],status:'suspected'}},{type:'video',time:'2026-02-01',text:'second',topic_labels:[],assessment:{risk_labels:['sexual'],status:'suspected'}}];
const result=aggregate(records,catalog);
assert.equal(result.total,3);assert.equal(result.labels[0].count,1);
assert.equal(result.labels.reduce((a,b)=>a+b.share,0),1);
assert.equal(aggregate(records,catalog,'risk').total,2);
assert.equal(aggregate([],catalog).total,0);
const filters={source:'all',status:'all',search:'',from:'',to:'2026-01-31',topicTag:'',riskTag:''};
assert.equal(filterRecords(records,filters,catalog).length,1);
filters.to='';filters.riskTag='sexual';assert.equal(filterRecords(records,filters,catalog)[0].type,'video');
filters.riskTag='';filters.topicTag='game';assert.equal(filterRecords(records,filters,catalog)[0].type,'comment');
filters.riskTag='sexual';assert.equal(filterRecords(records,filters,catalog).length,0);
const more=aggregate([...records,records[1]],catalog);
assert.equal(more.labels.find(x=>x.id==='sexual').share,.5);
console.log('Dashboard count, share, scope, dedup and filter checks passed.');
assert.equal(spaceStatus({state:'unavailable',status:'unknown'}),'无法确认');
assert.equal(spaceStatus({state:'partial',status:'clues_found'}),'发现留言线索 · 需核对');
const pendingRecords=[{...records[0],topic_candidates:[{label:'politics'}]},records[1]];
assert.equal(filterRecords(pendingRecords,{source:'all',status:'all',topicState:'pending'},catalog).length,1);
assert.equal(aggregate(pendingRecords,catalog,'topic').total,1);
const meaningRecords=[{...records[0],assessment:{...records[0].assessment,risk_labels:[],context_candidates:[{label:'sexualized',quote:'synthetic'}]}},records[1]];
assert.equal(filterRecords(meaningRecords,{source:'all',status:'meaning_pending'},catalog).length,1);
assert.equal(aggregate(meaningRecords,catalog,'risk').total,1);

// Exercise the UI controller with a minimal DOM double (no browser/network).
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
class Element {
  constructor(){this.children=[];this.style={};this.listeners={};this.value='';this.textContent='';this.hidden=false;this.attrs={};}
  append(...elements){this.children.push(...elements);}
  replaceChildren(...elements){this.children=[...elements];}
  addEventListener(type,listener){this.listeners[type]=listener;}
  setAttribute(key,value){this.attrs[key]=value;}
}
const uiCatalog={insult:{kind:'risk',name:'辱骂'},sexual:{kind:'risk',name:'性化表达'},game:{kind:'topic',name:'游戏'}};
const uiRecords=records.map((r,i)=>({...r,id:'r_'+i,assessment:{...r.assessment,model_checked:false,reason:'test',target:'unknown',method:'rules',evidence:[]},source_context:{state:'not_requested'},audit:[],errors:[]}));
const report={uid:'demo',demo:true,generated_at:'2026-01-01',mode:'offline',catalog:uiCatalog,records:uiRecords,coverage:{},context_review:{attempted:0,eligible:2},deduplicated_or_empty:0,errors:[],space_review:{state:'partial',status:'clues_found',coverage:{posts_checked:1,comments_checked:2},observations:[{text:'你这个废物',target:'owner',clues:[{name:'疑似攻击性留言'}],interpretation:'其他人留言',source_url:'https://t.bilibili.com/100?comment_on=1&comment_root_id=1#reply1'}]}};
const elements=new Map();
function get(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);}
get('report-data').textContent=JSON.stringify(report);
let interval;
const context={document:{getElementById:get,createElement:()=>new Element()},setInterval:callback=>{interval=callback;return 1;},clearInterval:()=>{interval=null;},setTimeout:()=>{},console};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../aicu/assets/dashboard.js'),'utf8'),context);
assert.equal(get('metrics').children[0].children[1].textContent,'2');
assert.equal(get('assignments-topic').textContent,1);
assert.equal(get('assignments-risk').textContent,2);
assert.equal(get('legend-topic').children.length,1);
assert.equal(get('legend-risk').children.length,2);
assert.equal(get('space-status').textContent,'发现留言线索 · 需核对');
assert.equal(get('space-evidence').children.length,1);
get('source').value='video';get('source').listeners.change();
assert.equal(get('metrics').children[0].children[1].textContent,'1');
assert.equal(get('assignments-topic').textContent,0);
assert.equal(get('assignments-risk').textContent,1);
get('reset').onclick();get('timeline').value=0;get('timeline').oninput();
assert.equal(get('metrics').children[0].children[1].textContent,'0');
assert.equal(get('empty-topic').hidden,false);
assert.equal(get('empty-risk').hidden,false);
get('play').onclick();interval();
assert.equal(get('metrics').children[0].children[1].textContent,'1');
get('reset').onclick();get('legend-topic').children[0].onclick();
assert.equal(get('clear-topic').hidden,false);
assert.equal(get('metrics').children[0].children[1].textContent,'1');
get('legend-risk').children[0].onclick();
assert.equal(get('clear-risk').hidden,false);
assert.equal(get('metrics').children[0].children[1].textContent,'1');
get('clear-topic').onclick();
assert.equal(get('clear-topic').hidden,true);
get('clear-risk').onclick();
assert.equal(get('metrics').children[0].children[1].textContent,'2');
console.log('UI controller dual rings, source filtering, empty state, timeline playback and tag linkage passed.');
