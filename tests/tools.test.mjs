import test from 'node:test';
import assert from 'node:assert/strict';
import {MapTools} from '../frontend/tools.js';

test('drawing, point selection, cancellation, and clearing preserve the intended geometry',()=>{
    const layer=()=>({addTo(){return this;},clearLayers(){},setLatLng(){},bindPopup(){return this;}});
    globalThis.L={layerGroup:layer,polygon:layer,marker:layer,circleMarker:layer,polyline:layer};
    globalThis.document={addEventListener(){}};
    const map={on(){},removeLayer(){},getContainer:()=>({style:{}})};
    const events=[];
    const tools=new MapTools(map,{message(){},polygon:p=>events.push(p),point(){}});
    const polygon={type:'Polygon',coordinates:[[[0,0],[1,0],[1,1],[0,0]]]};
    tools.setPolygon(polygon);
    tools.activate('area');tools.cancel();assert.equal(tools.polygon,polygon);
    tools.activate('point');tools.setTarget(0,0);tools.cancel();assert.deepEqual(tools.target,{lat:0,lng:0});
    assert.equal(tools.polygon,polygon);
    tools.activate('area');tools.vertices=[{lat:0,lng:0},{lat:0,lng:1},{lat:1,lng:1}];tools.finish();
    assert.equal(tools.mode,null);assert.deepEqual(tools.polygon.coordinates[0][0],tools.polygon.coordinates[0].at(-1));
    tools.clearPolygon();assert.equal(tools.polygon,null);assert.equal(events.at(-1),null);
});
