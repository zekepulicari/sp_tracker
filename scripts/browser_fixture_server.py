"""Offline acceptance server with partial RF predictors, never wildlife forecasts."""
import argparse
import sys
from pathlib import Path
from datetime import date,timedelta
import json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fixtures import synthetic_records
from main import app
from analysis import prediction
from upstream import gateway
from fastapi.responses import HTMLResponse
import uvicorn

async def observations_fixture(url,params=None):
    params=params or {}
    if url.endswith('taxa/autocomplete'):
        return {'results':[{'id':9000001,'name':'Fixture terrestrial animal','preferred_common_name':'Synthetic test animal','rank':'species','ancestor_ids':[1]}]}
    if url.endswith('/observations'):
        rows=[]
        for i in range(60):
            lat=.2+(i%6)*.05
            lng=.2+(i//6)*.04
            rows.append({'id':i+1,'observed_on':f'2024-{date.today().month:02d}-{i%25+1:02d}',
                'geojson':{'coordinates':[lng,lat]},'quality_grade':'research','captive':False,
                'taxon':{'id':9000001+i%12,'name':f'Fixture animal {i%12+1}',
                    'preferred_common_name':f'Synthetic animal {i%12+1}','rank':'species','ancestor_ids':[1], 'iconic_taxon_name':'Mammalia'}})
        return {'total_results':60,'results':rows}
    raise ValueError('Unexpected external request in offline acceptance mode.')

async def local_fixture(request,progress):
    points=[{**r,'month':int(r['date'][5:7])} for r in synthetic_records(request.environment) if r['presence']==1]
    return points,5,{'complete':True,'notice':'Synthetic acceptance fixture; no live sightings.'}

async def aligned_fixture(points,environment,progress,retain_partial=False):
    rows = synthetic_records(environment)
    if retain_partial:
        from analysis.features import ENVIRONMENTS
        for i in range(0, len(rows), 7):
            rows[i][ENVIRONMENTS[environment][0]] = None
    return rows,[]

async def weather_fixture(lat,lng,start,end,environment,forecast=False):
    from analysis.features import ENVIRONMENTS
    return {str(start+timedelta(days=i)):{key:14+i*.6 for key in ENVIRONMENTS[environment]} for i in range((end-start).days+1)},['Synthetic test weather, not a real forecast.']

@app.get('/fixture',response_class=HTMLResponse)
def fixture_page():
    html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8-sig')
    banner='<p role="alert" style="position:sticky;top:0;z-index:2000;margin:0;padding:10px;background:#fff0a8;color:#222;font-weight:bold">OFFLINE ACCEPTANCE FIXTURE — synthetic data, not wildlife evidence.</p>'
    return html.replace('<body>','<body>'+banner)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ack-synthetic',action='store_true',required=True)
    parser.parse_args()
    # The production static catch-all is last in main; put this test-only route before it.
    fixture_route = next(route for route in app.router.routes if getattr(route, 'path', '') == '/fixture')
    app.router.routes.remove(fixture_route)
    app.router.routes.insert(0, fixture_route)
    gateway.get=observations_fixture
    prediction.collect_local=local_fixture
    prediction.align_history=aligned_fixture
    prediction.environmental_days=weather_fixture
    prediction.generate_interpretation=lambda species,evidence,fallback,api_key=None:{'text':fallback,'source':'fixture','notice':'Synthetic acceptance fixture, not an ecological forecast.'}
    import analysis.discovery as discovery
    discovery.environmental_days=weather_fixture
    uvicorn.run(app,host='127.0.0.1',port=8002)
