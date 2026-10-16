"""Complete seasonal observation counts inside a user-drawn polygon."""
from collections import defaultdict
from datetime import date, timedelta
from cachetools import TTLCache
from analysis.data_ingestion import INAT, evidence_window, fetch_observations, parse_observation, environmental_days, timestamp
from analysis.geo import validate_polygon, inside, polygon_area
from upstream import gateway, UpstreamError
from config import DISCOVERY_CAP

history_cache = TTLCache(maxsize=100, ttl=86400)
taxa_cache = TTLCache(maxsize=1000, ttl=86400)
GROUPS = {'all': None, 'birds': 'Aves', 'mammals': 'Mammalia', 'reptiles': 'Reptilia',
          'amphibians': 'Amphibia', 'fish': 'Actinopterygii', 'insects': 'Insecta',
          'arachnids': 'Arachnida', 'mollusks': 'Mollusca'}


async def species_taxon(taxon):
    if taxon.get('rank') == 'species':
        return taxon
    if taxon.get('rank') != 'subspecies':
        return None
    taxon_id = taxon['id']
    if taxon_id not in taxa_cache:
        data = await gateway.get(f'{INAT}/taxa/{taxon_id}')
        rows = data.get('results', [])
        if not rows:
            raise UpstreamError('Could not resolve species identity. Please retry.')
        taxa_cache[taxon_id] = next((a for a in rows[0].get('ancestors', []) if a.get('rank') == 'species'), None)
    return taxa_cache[taxon_id]


async def rank_observations(rows, polygon, month, group='all'):
    grouped = {}
    seen = set()
    for obs in rows:
        record = parse_observation(obs)
        taxon = obs.get('taxon') or {}
        if (not record or record['id'] in seen or record['month'] != month or
            obs.get('captive') or obs.get('quality_grade') != 'research' or
            not inside(polygon, record['lat'], record['lng'])):
            continue
        # Do not trust an upstream filter alone: exclude taxa outside Animalia.
        if 1 not in taxon.get('ancestor_ids', []) and taxon.get('id') != 1:
            continue
        if GROUPS[group] and taxon.get('iconic_taxon_name') != GROUPS[group]:
            continue
        species = await species_taxon(taxon)
        if not species:
            continue
        seen.add(record['id'])
        key = species['id']
        if key not in grouped:
            grouped[key] = {'taxon_id': key, 'name': species['name'],
                            'common_name': species.get('preferred_common_name', ''),
                            'dates': set(), 'years': set(), 'count': 0}
        entry = grouped[key]
        entry['count'] += 1
        entry['dates'].add(record['date'])
        entry['years'].add(int(record['date'][:4]))
    ordered = sorted(grouped.values(), key=lambda s: (-s['count'], -len(s['dates']), s['taxon_id']))[:10]
    results = []
    for rank, entry in enumerate(ordered, 1):
        dates, years = entry.pop('dates'), entry.pop('years')
        results.append({**entry, 'rank': rank, 'distinct_dates': len(dates), 'years': sorted(years),
            'latest_sighting': max(dates), 'evidence_label': 'Single recorded sighting' if entry['count'] == 1 else f"{entry['count']} recorded sightings",
            'source_url': f"https://www.inaturalist.org/taxa/{entry['taxon_id']}"})
    return results, len(seen)


async def run_discovery(request, progress):
    polygon = validate_polygon(request.polygon.coordinates)
    start, end = evidence_window()
    month = request.target_date.month
    key = (polygon.wkt, month, request.animal_group, str(start), str(end))
    if key not in history_cache:
        minx, miny, maxx, maxy = polygon.bounds
        params = {'taxon_id': 1, 'quality_grade': 'research', 'captive': 'false', 'geo': 'true',
                  'month': month, 'd1': str(start), 'd2': str(end),
                  'swlng': minx, 'swlat': miny, 'nelng': maxx, 'nelat': maxy}
        if GROUPS[request.animal_group]:
            params['iconic_taxa'] = GROUPS[request.animal_group]
        rows, total, complete = await fetch_observations(params, DISCOVERY_CAP, require_complete=True, progress=progress)
        species, count = await rank_observations(rows, polygon, month, request.animal_group)
        history_cache[key] = {'species': species, 'records_inside': count,
            'bbox_records': total, 'complete': complete, 'fetched_at': timestamp()}
    cached = history_cache[key]
    # A point guaranteed to be inside the area, not a vertex-average centroid.
    point = polygon.representative_point()
    weather = {'available': False, 'reason': 'Date is outside the supported weather forecast window.'}
    warnings = []
    if date.today() <= request.target_date <= date.today() + timedelta(days=6):
        progress('Fetching weather context separately from the seasonal ranking…')
        try:
            days, warnings = await environmental_days(point.y, point.x, request.target_date,
                request.target_date, 'terrestrial', forecast=True)
            conditions = days[str(request.target_date)]
            weather = {'available': all(v is not None for v in conditions.values()),
                       'conditions': conditions, 'provenance': 'forecast',
                       'location': {'lat': point.y, 'lng': point.x},
                       'reason': 'Representative point weather; conditions can vary across the area.'}
        except UpstreamError:
            warnings.append('Weather context is unavailable. Historical ranking is unchanged.')
    return {'type': 'seasonal_discovery', 'title': 'Most recorded animals here in this season.',
        'target_date': str(request.target_date), 'month': month, 'animal_group': request.animal_group,
        'polygon': request.polygon.model_dump(), 'area_km2': round(polygon_area(polygon), 3),
        'analysis_location': {'lat': point.y, 'lng': point.x},
        **cached, 'evidence_window': {'start': str(start), 'end': str(end)}, 'weather': weather,
        'warnings': warnings + ['Recording frequency reflects observer activity as well as wildlife occurrence. Weather does not change this ranking.'],
        'summary': 'No matching recorded sightings. This does not mean no animals live here.' if not cached['species'] else 'Historical seasonal sightings suggest these animals as candidates to look for; they are not guaranteed encounters.'}
