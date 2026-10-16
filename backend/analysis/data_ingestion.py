"""Historical sightings and environmental data, with explicit completeness."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from cachetools import TTLCache
from analysis.features import FEATURES, ENVIRONMENTS, aggregate
from analysis.geo import distance_km
from upstream import gateway, UpstreamError

INAT = 'https://api.inaturalist.org/v1'
WEATHER_ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
WEATHER_FORECAST = 'https://api.open-meteo.com/v1/forecast'
MARINE = 'https://marine-api.open-meteo.com/v1/marine'
env_cache = TTLCache(maxsize=10000, ttl=86400)


def evidence_window(today=None):
    today = today or date.today()
    end = today - timedelta(days=1)
    try:
        start = today.replace(year=today.year - 10)
    except ValueError:
        start = today.replace(year=today.year - 10, day=28)
    return start, end


def parse_observation(obs):
    coords = (obs.get('geojson') or {}).get('coordinates')
    if not coords or len(coords) != 2 or not obs.get('observed_on'):
        return None
    try:
        day = date.fromisoformat(obs['observed_on'][:10])
        lng, lat = map(float, coords)
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            return None
    except (ValueError, TypeError):
        return None
    return {'id': obs['id'], 'lat': lat, 'lng': lng, 'date': day.isoformat(),
            'month': day.month, 'presence': 1}


async def fetch_observations(params, cap, require_complete=False, progress=None):
    """Never silently truncate complete discovery queries or failed pages."""
    records, seen = [], set()
    page = 1
    expected = None
    while True:
        data = await gateway.get(f'{INAT}/observations', {
            **params, 'per_page': 200, 'page': page, 'order_by': 'id', 'order': params.get('order', 'asc')})
        total = data.get('total_results')
        if not isinstance(total, int) or not isinstance(data.get('results'), list):
            raise UpstreamError('Incomplete sightings response. Please try again.')
        if expected is None:
            expected = total
        if require_complete and (total > cap or total != expected):
            raise UpstreamError('Too many or changing sightings. Narrow the area and try again.')
        rows = data['results']
        before = len(seen)
        for obs in rows:
            if obs.get('id') is not None and obs['id'] not in seen:
                seen.add(obs['id'])
                records.append(obs)
        if progress:
            progress(f'Retrieved {len(records)} of {total} sightings…')
        if len(seen) >= total:
            return records[:cap], total, len(seen) >= total
        if not require_complete and len(records) >= cap:
            return records[:cap], total, False
        if len(rows) < 200 or len(seen) == before:
            raise UpstreamError('Sightings pagination was incomplete. Please retry or narrow the area.')
        page += 1


async def local_occurrences(taxon_id, lat, lng, radius, limit, progress):
    start, end = evidence_window()
    params = {'taxon_id': taxon_id, 'lat': lat, 'lng': lng, 'radius': radius,
              'quality_grade': 'research', 'captive': 'false', 'geo': 'true',
              'd1': start.isoformat(), 'd2': end.isoformat(), 'order': 'desc'}
    rows, total, complete = await fetch_observations(params, limit, progress=progress)
    records, seen = [], set()
    for row in rows:
        record = parse_observation(row)
        if record and record['id'] not in seen and distance_km(lat, lng, record['lat'], record['lng']) <= radius:
            records.append(record)
            seen.add(record['id'])
    return records, {'upstream_total': total, 'complete': complete,
                     'fetched_records': len(rows), 'unusable_records': len(rows) - len(records)}


def _source_days(environment, source):
    return [key for key in ENVIRONMENTS[environment] if FEATURES[key]['source'] == source]


async def environmental_days(lat, lng, start, end, environment, forecast=False):
    """Use hourly UTC data for both training and forecasts; no proxy imputation."""
    start = date.fromisoformat(str(start))
    end = date.fromisoformat(str(end))
    result = {str(start + timedelta(days=i)): {} for i in range((end-start).days + 1)}
    warnings = []
    for source in ('weather', 'marine'):
        keys = _source_days(environment, source)
        if not keys:
            continue
        # SMOC SST/currents coverage starts January 2022. Archive weather lags several days.
        if not forecast and ((source == 'marine' and start < date(2022, 1, 1)) or
                             (source == 'weather' and end > date.today() - timedelta(days=5))):
            warnings.append(f'{source.title()} historical data is unavailable for this date range.')
            continue
        url = MARINE if source == 'marine' else (WEATHER_FORECAST if forecast else WEATHER_ARCHIVE)
        params = {'latitude': lat, 'longitude': lng, 'start_date': str(start), 'end_date': str(end),
                  'hourly': ','.join(FEATURES[k]['variable'] for k in keys), 'timezone': 'GMT',
                  'wind_speed_unit': 'kmh', 'cell_selection': 'nearest'}
        if source == 'marine':
            params.pop('wind_speed_unit')
            params['velocity_unit'] = 'kmh'
        try:
            data = await gateway.get(url, params)
            hourly = data.get('hourly', {})
            times = hourly.get('time', [])
            for day in result:
                indexes = [i for i, t in enumerate(times) if t[:10] == day]
                for key in keys:
                    values = hourly.get(FEATURES[key]['variable'], [])
                    selected = [values[i] for i in indexes if i < len(values)]
                    result[day][key] = aggregate(selected, key)
        except UpstreamError as exc:
            if 'budget' in str(exc).lower() or 'quota' in str(exc).lower():
                raise
            warnings.append(f'{source.title()} data unavailable: {exc}')
    for conditions in result.values():
        for key in ENVIRONMENTS[environment]:
            conditions.setdefault(key, None)
    return result, warnings


async def align_history(points, environment, progress):
    lock = asyncio.Semaphore(4)
    completed = 0
    excluded = []
    aligned = []

    async def fetch(point):
        nonlocal completed
        async with lock:
            key = (round(point['lat'], 4), round(point['lng'], 4), point['date'], environment)
            if key not in env_cache:
                days, _ = await environmental_days(point['lat'], point['lng'], point['date'], point['date'], environment)
                conditions = days[point['date']]
                if all(v is not None for v in conditions.values()):
                    env_cache[key] = conditions
            else:
                conditions = dict(env_cache[key])
        missing = [k for k, v in conditions.items() if v is None]
        if missing:
            excluded.append({'id': point['id'], 'date': point['date'], 'missing': missing})
        else:
            aligned.append({**point, **conditions})
        completed += 1
        if completed % 20 == 0 or completed == len(points):
            progress(f'Aligning environmental evidence: {completed}/{len(points)}')

    tasks = [asyncio.create_task(fetch(point)) for point in points]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    # Network completion order must not change the split or fitted model.
    return sorted(aligned, key=lambda p: str(p['id'])), sorted(excluded, key=lambda p: str(p['id']))


def timestamp():
    return datetime.now(timezone.utc).isoformat()
