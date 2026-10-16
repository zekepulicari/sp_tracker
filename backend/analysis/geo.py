"""WGS84 geometry: ellipsoidal distances/areas, polygon boundary checks."""
import math
import random
from pyproj import Geod
from shapely.geometry import Polygon, Point

GEOD = Geod(ellps='WGS84')

def validate_polygon(coordinates: list) -> Polygon:
    if len(coordinates) != 1:
        raise ValueError('Provide one polygon without holes.')
    ring = coordinates[0]
    if not 4 <= len(ring) <= 101 or ring[0] != ring[-1]:
        raise ValueError('Close the polygon and use 3–100 vertices.')
    for pt in ring:
        if len(pt) != 2 or not all(math.isfinite(v) for v in pt):
            raise ValueError('Coordinates must be finite longitude/latitude pairs.')
        if not -180 <= pt[0] <= 180 or not -90 <= pt[1] <= 90:
            raise ValueError('Coordinates are outside WGS84 bounds.')
    if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
        raise ValueError('Antimeridian-crossing polygons are not supported.')
    polygon = Polygon(ring)
    if not polygon.is_valid or polygon.area == 0:
        raise ValueError('Draw a nonzero area without intersecting edges.')
    return polygon

def polygon_area(polygon: Polygon) -> float:
    return abs(GEOD.geometry_area_perimeter(polygon)[0]) / 1_000_000

def inside(polygon: Polygon, lat: float, lng: float) -> bool:
    return polygon.covers(Point(lng, lat))

def distance_km(lat: float, lng: float, other_lat: float, other_lng: float) -> float:
    return GEOD.inv(lng, lat, other_lng, other_lat)[2] / 1000

def background_samples(records: list, lat: float, lng: float, radius: float, seed=42) -> list:
    rng = random.Random(seed)
    dates = sorted({r['date'] for r in records})
    samples = []
    for idx in range(len(records)):
        x, y, _ = GEOD.fwd(lng, lat, rng.uniform(0, 360), radius * 1000 * math.sqrt(rng.random()))
        samples.append({'id': f'background-{idx}', 'lat': y, 'lng': x,
                        'date': rng.choice(dates), 'presence': 0})
    return samples
