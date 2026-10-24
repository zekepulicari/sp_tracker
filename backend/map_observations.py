"""Small, bounded iNaturalist responses for interactive map browsing only."""
import asyncio
import math
from cachetools import TTLCache
from fastapi import HTTPException
from upstream import gateway, UpstreamError

INAT_MAP = 'https://api.inaturalist.org/v2'
MAP_TIMEOUT = 10
MAP_FIELDS = 'id,geojson,observed_on,taxon.name,user.login,place_guess'
PHOTO_FIELDS = ('id,observation_photos.position,observation_photos.photo.url,'
                'observation_photos.photo.medium_url,observation_photos.photo.attribution,'
                'observation_photos.photo.license_code')
map_cache = TTLCache(maxsize=256, ttl=3600)
inflight = {}


def compact_record(row):
    if not isinstance(row, dict):
        return None
    coordinates = (row.get('geojson') or {}).get('coordinates')
    if not isinstance(row.get('id'), int) or not isinstance(coordinates, list) or len(coordinates) != 2:
        return None
    try:
        lng, lat = map(float, coordinates)
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            return None
    except (TypeError, ValueError):
        return None
    return {'id': row['id'], 'geojson': {'type': 'Point', 'coordinates': [lng, lat]},
            'observed_on': row.get('observed_on'), 'taxon': {'name': (row.get('taxon') or {}).get('name')},
            'user': {'login': (row.get('user') or {}).get('login')}, 'place_guess': row.get('place_guess')}


def observation_page(data):
    if not isinstance(data, dict):
        raise HTTPException(503, detail='Map data was incomplete. Please retry.')
    rows, total = data.get('results'), data.get('total_results')
    if not isinstance(rows, list) or not isinstance(total, int) or total < 0:
        raise HTTPException(503, detail='Map data was incomplete. Please retry.')
    records = [record for row in rows[:100] if (record := compact_record(row)) is not None]
    return {'results': records, 'total_results': total, 'sample_cap': 100,
            'complete': total == len(records)}


def observation_photo(data):
    if not isinstance(data, dict):
        raise HTTPException(503, detail='Photo details were incomplete. Please retry.')
    rows = data.get('results')
    if not isinstance(rows, list):
        raise HTTPException(503, detail='Photo details were incomplete. Please retry.')
    if not rows:
        raise HTTPException(404, detail='This observation is no longer available.')
    photos = []
    for item in sorted(rows[0].get('observation_photos') or [], key=lambda item: item.get('position') or 0):
        photo = item.get('photo') or {}
        if photo.get('medium_url') or photo.get('url'):
            photos.append({'url': photo.get('medium_url') or photo['url'],
                           'attribution': photo.get('attribution'), 'license_code': photo.get('license_code')})
            break
    return {'id': rows[0].get('id'), 'photos': photos}


async def _load(key, path, params, transform):
    try:
        async with asyncio.timeout(MAP_TIMEOUT):
            result = transform(await gateway.get(f'{INAT_MAP}/{path}', params))
            map_cache[key] = result
            return result
    except TimeoutError:
        raise HTTPException(504, detail='Observations took too long to load. Please retry.') from None
    except UpstreamError as exc:
        raise HTTPException(503, detail=str(exc)) from None


async def cached_map_get(path, params, transform):
    key = (path, tuple(sorted(params.items())))
    if key in map_cache:
        return map_cache[key]
    if key not in inflight:
        task = asyncio.create_task(_load(key, path, params, transform))
        inflight[key] = task
        def finished(done):
            if inflight.get(key) is done:
                inflight.pop(key, None)
            if not done.cancelled():
                done.exception()  # Observe failures even if every browser has disconnected.
        task.add_done_callback(finished)
    # One browser cancelling must not cancel a request shared with another browser.
    return await asyncio.shield(inflight[key])


async def map_observations(taxon_id, bounds):
    if bounds is not None:
        north, east, south, west = bounds
        # A complete larger result covers a smaller view; a capped sample never does.
        for (path, pairs), page in list(map_cache.items()):
            params = dict(pairs)
            if path != 'observations' or params.get('taxon_id') != taxon_id or not page['complete']:
                continue
            if not all(k in params for k in ('nelat', 'nelng', 'swlat', 'swlng')):
                continue
            if params['nelat'] >= north and params['nelng'] >= east and params['swlat'] <= south and params['swlng'] <= west:
                rows = [r for r in page['results'] if west <= r['geojson']['coordinates'][0] <= east
                        and south <= r['geojson']['coordinates'][1] <= north]
                return {**page, 'results': rows, 'total_results': len(rows)}
    params = {'taxon_id': taxon_id, 'per_page': 100, 'geo': 'true', 'captive': 'false', 'fields': MAP_FIELDS}
    if bounds is not None:
        params.update(zip(('nelat', 'nelng', 'swlat', 'swlng'), bounds))
    return await cached_map_get('observations', params, observation_page)


async def map_photo(observation_id):
    # v2 detail paths use UUIDs; the search endpoint also accepts the public numeric ID.
    return await cached_map_get('observations', {'id': observation_id, 'fields': PHOTO_FIELDS}, observation_photo)


async def close_map_requests():
    tasks = list(inflight.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    inflight.clear()
