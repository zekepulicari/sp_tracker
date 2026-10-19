import test from 'node:test';
import assert from 'node:assert/strict';
import {setupApiSettings} from '../frontend/settings.js';

function harness({busy=false, secure=true, previous=true}={}) {
    const elements=new Map();
    const element=id=>{
        if (!elements.has(id)) elements.set(id,{value:'',textContent:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}});
        return elements.get(id);
    };
    globalThis.document={getElementById:element};
    const forbiddenStorage={getItem(){throw Error('No credential storage');},setItem(){throw Error('No credential storage');}};
    globalThis.window={isSecureContext:secure,localStorage:forbiddenStorage,sessionStorage:forbiddenStorage};
    let reruns=0, navigations=0;
    const settings=setupApiSettings({isBusy:()=>busy,rerun(){reruns++;return previous;},explore(){navigations++;}});
    return {element,settings,counts:()=>[reruns,navigations],apply(key){element('gemini-api-key').value=key;element('api-key-form').listeners.submit({preventDefault(){}});}};
}

test('personal key applies in memory, reruns once, clears the input, and can be removed',()=>{
    const h=harness();h.apply('personal-test-key');
    assert.deepEqual(h.settings.headers(),{'X-Gemini-Key':'personal-test-key'});
    assert.equal(h.element('gemini-api-key').value,'');
    assert.deepEqual(h.counts(),[1,1]);
    h.element('clear-api-key').listeners.click();
    assert.deepEqual(h.settings.headers(),{});
    assert.deepEqual(harness().settings.headers(),{});
});

test('busy jobs, insecure transport, and invalid keys cannot apply or rerun',()=>{
    for (const options of [{busy:true},{secure:false},{}]) {
        const h=harness(options);h.apply(Object.keys(options).length?'personal-test-key':'bad key');
        assert.deepEqual(h.settings.headers(),{});assert.deepEqual(h.counts(),[0,0]);
    }
});

test('first-time key setup stays in settings with a useful next step',()=>{
    const h=harness({previous:false});h.apply('personal-test-key');
    assert.deepEqual(h.counts(),[1,0]);
    assert(h.element('api-key-status').textContent.includes('Choose an animal'));
});
