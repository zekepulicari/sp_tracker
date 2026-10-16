"""Controlled fixtures, deliberately not presented as ecological observations."""
from datetime import date,timedelta
import numpy as np
from analysis.features import ENVIRONMENTS

def synthetic_records(environment):
    rng=np.random.default_rng(42)
    rows=[]
    for i in range(240):
        presence=i%2
        day=date(2023,1,1)+timedelta(days=i//2)
        row={'id':f'fixture-{i}','presence':presence,'date':str(day),
             'lat':(i//2%12)*.2,'lng':(i//24)*.2}
        for key in ENVIRONMENTS[environment]:
            row[key]=float(10+presence*8+rng.normal(0,2))
        rows.append(row)
    return rows
