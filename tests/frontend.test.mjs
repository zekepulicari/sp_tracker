import test from 'node:test';
import assert from 'node:assert/strict';
import {Selection, escapeHtml, safeUrl} from '../frontend/state.js';
import {resultHtml, setupAnalysis} from '../frontend/analysis.js';
const storage = () => {const values=new Map();return {getItem:k=>values.get(k) ?? null,setItem:(k,v)=>values.set(k,v)};};

test('resolved identity survives refresh; typing invalidates without replacing the saved selection',()=>{
    const memory=storage(),first=new Selection(memory);
    first.select({id:42,name:'Example animal',common_name:'Example'});
    first.invalidate(); assert.equal(first.species,null);
    assert.equal(new Selection(memory).species.id,42);
});
test('environment persists and invalid storage falls back safely',()=>{
    const memory=storage(),state=new Selection(memory);
    state.setEnvironment('marine');assert.equal(new Selection(memory).environment,'marine');
    memory.setItem('sp-tracker:last-species','bad JSON');assert.equal(new Selection(memory).species.id,41521);
    assert.equal(new Selection(null).environment,'terrestrial');
});
test('external text and URL protocols render safely',()=>{
    assert.equal(safeUrl('javascript:alert(1)'), '');assert.equal(safeUrl('http://example.com'), '');
    assert.equal(escapeHtml('<script>"&'), '&lt;script&gt;&quot;&amp;');
    const html=resultHtml({type:'historical_profile',summary:'<img src=x onerror=alert(1)>',warnings:['<script>bad</script>'],interpretation:{text:'<svg onload=alert(1)>',notice:'fallback'},profile:[]});
    assert(!html.includes('<script>') && !html.includes('<svg'));
    assert(html.includes('&lt;img'));
});
test('Key Factors displays feature importance without encounter percentages',()=>{
    const html=resultHtml({summary:'Associations',warnings:[],model:{variable_importance:{air_temp:.8,wind_speed:.2}},profile:[]});
    assert(html.includes('80.0%') && html.includes('class="bar"'));
    assert(html.includes('Relative feature importance'));
});

class Element {
    constructor(id){this.id=id;this.value='';this.hidden=false;this.disabled=false;this.innerHTML='';this.textContent='';this.listeners={};this.attributes={};}
    addEventListener(name,fn){this.listeners[name]=fn;}
    setAttribute(key,value){this.attributes[key]=value;}
    checkValidity(){return true;}
    querySelectorAll(){return [];}
    focus(){}
}
function harness(saved=null){
    const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
    globalThis.document={getElementById:element};
    const session=storage();if(saved)session.setItem('sp-tracker:task',JSON.stringify(saved));
    globalThis.window={sessionStorage:session};
    const selection=new Selection(storage());selection.select({id:42,name:'Chosen animal'});
    element('prediction-date').value='2026-10-16';element('analysis-method').value='glm';element('analysis-limit').value='200';
    const context={selection,tools:{target:{lat:1,lng:2},cancel(){},setTarget(lat,lng){this.target={lat,lng};},setPolygon(value){this.polygon=value;}},choose:value=>selection.select(value),map:{}};
    return {element,session,context};
}
async function flush(){for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));}

test('running analysis preserves selected taxon without a second autocomplete lookup',async()=>{
    const h=harness();const calls=[];
    globalThis.fetch=async(path,options)=>{
        calls.push([path,options]);
        if(options)return {ok:true,json:async()=>({task_id:'task'})};
        if(path.includes('status'))return {ok:true,json:async()=>({status:'complete',progress:'done'})};
        return {ok:true,json:async()=>({type:'historical_profile',summary:'Done',warnings:[],profile:[]})};
    };
    setupAnalysis(h.context);h.element('btn-run-analysis').listeners.click();await flush();
    assert.equal(JSON.parse(calls[0][1].body).taxon_id,42);
    assert(!calls.some(([path])=>path.includes('species/search')));
    assert.equal(h.element('btn-run-analysis').disabled,false);
    assert(h.element('analysis-results').innerHTML.includes('Done'));
});
test('unresolved typed text cannot launch analysis',()=>{
    const h=harness();h.context.selection.invalidate();setupAnalysis(h.context);
    h.element('btn-run-analysis').listeners.click();
    assert(h.element('analysis-results').innerHTML.includes('Choose an animal'));
});
test('refresh resumes stored task and clears session when complete',async()=>{
    const saved={id:'previous',path:'/api/analysis/run',payload:{taxon_id:42,species:'Chosen animal',environment:'marine',target_lat:1,target_lng:2,target_date:'2026-10-16',method:'glm',limit:200}};
    const h=harness(saved);const calls=[];
    globalThis.fetch=async path=>{calls.push(path);return {ok:true,json:async()=>path.includes('status')?{status:'complete',progress:'done'}:{type:'historical_profile',summary:'Resumed evidence',warnings:[],profile:[]}};};
    setupAnalysis(h.context);await flush();
    assert(calls[0].includes('previous'));
    assert.equal(h.session.getItem('sp-tracker:task'),'null');
    assert(h.element('analysis-results').innerHTML.includes('Resumed evidence'));
});
test('server restart produces a clear recovery message',async()=>{
    const h=harness({id:'gone',path:'/api/analysis/run',payload:{taxon_id:42,species:'Chosen animal',environment:'marine',target_lat:1,target_lng:2,target_date:'2026-10-16',method:'glm',limit:200}});
    globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'The server may have restarted; run the analysis again.'})});
    setupAnalysis(h.context);await flush();
    assert(h.element('analysis-results').innerHTML.includes('server may have restarted'));
    assert.equal(h.element('btn-run-analysis').disabled,false);
});
