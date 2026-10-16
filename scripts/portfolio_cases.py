"""Reproducible public study locations; saves actual results, including failures."""
import argparse
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
# Portfolio checks use the deterministic explanation and never consume AI tokens.
os.environ['GEMINI_KEY']=''
from main import AnalysisRequest
from analysis.prediction import run_analysis
from analysis.probability_model import train_model
from upstream import gateway

CASES=[
    {'slug':'marine-orca','species':'Orcinus orca','taxon_id':41521,'environment':'marine','target_lat':48.5,'target_lng':-123.1},
    {'slug':'terrestrial-puma','species':'Puma concolor','taxon_id':42007,'environment':'terrestrial','target_lat':37.4,'target_lng':-122.2},
]

async def main():
    for case in CASES:
        slug=case['slug']
        request=AnalysisRequest(**{k:v for k,v in case.items() if k!='slug'},target_date=date.today(),limit=100)
        print(f'Running {slug} with public sightings; no AI request.',flush=True)
        try:
            result=await run_analysis(request,lambda message:print(f'{slug}: {message}',flush=True))
        except ValueError as exc:
            result={'type':'live_check_unavailable','species':request.species,'environment':request.environment,
                    'checked_on':str(date.today()),'summary':str(exc),'validation':None,
                    'notice':'No predictive-performance claim can be made from an unavailable live check.'}
        output=ROOT/'docs'/'examples'/f'{slug}.json'
        output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        print(f'{slug}: {result["summary"]}',flush=True)
        print(f'Saved the actual check result: {output.name}',flush=True)
    await gateway.close()

def fixtures():
    from fixtures import synthetic_records
    for case in CASES:
        environment=case['environment']
        records=synthetic_records(environment)
        _,metadata=train_model(records,environment,'glm')
        result={'type':'synthetic_acceptance_example','environment':environment,
                'notice':'Artificial test data, not field observations. Metrics demonstrate validation behavior, not ecological predictive performance.',
                'seed':42,'records':len(records),'model':metadata}
        path=ROOT/'docs'/'examples'/f'synthetic-{environment}.json'
        path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        print(f'Saved {path.name}: synthetic acceptance example, not a real wildlife forecast.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--live',action='store_true',help='Fetch public iNaturalist/Open-Meteo data; up to roughly 600 environmental requests across both cases.')
    modes.add_argument('--fixtures',action='store_true',help='Write reproducible, explicitly synthetic acceptance examples without network access.')
    args=parser.parse_args()
    if args.live:asyncio.run(main())
    else:fixtures()
