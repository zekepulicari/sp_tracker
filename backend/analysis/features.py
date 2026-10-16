"""The single feature contract used for historical data and forecasts."""
import math

FEATURES = {
    'air_temp': {'source': 'weather', 'variable': 'temperature_2m', 'unit': '°C', 'label': 'Air temperature'},
    'wind_speed': {'source': 'weather', 'variable': 'wind_speed_10m', 'unit': 'km/h', 'label': 'Wind speed'},
    'precipitation': {'source': 'weather', 'variable': 'precipitation', 'unit': 'mm/day', 'label': 'Precipitation'},
    'sst': {'source': 'marine', 'variable': 'sea_surface_temperature', 'unit': '°C', 'label': 'Sea surface temperature'},
    'wave_height': {'source': 'marine', 'variable': 'wave_height', 'unit': 'm', 'label': 'Wave height'},
    'ocean_current_velocity': {'source': 'marine', 'variable': 'ocean_current_velocity', 'unit': 'km/h', 'label': 'Ocean current'},
}
ENVIRONMENTS = {
    'terrestrial': ['air_temp', 'wind_speed', 'precipitation'],
    'marine': ['sst', 'wind_speed', 'wave_height', 'ocean_current_velocity'],
}
SEASONAL = ['season_sin', 'season_cos']

def seasonality(month: int) -> dict:
    angle = 2 * math.pi * (month - 1) / 12
    return {'season_sin': math.sin(angle), 'season_cos': math.cos(angle)}

def aggregate(values: list, feature: str):
    """Require a complete day; sum rainfall and average every other predictor."""
    if len(values) != 24 or any(v is None or not math.isfinite(float(v)) for v in values):
        return None
    numbers = [float(v) for v in values]
    return sum(numbers) if feature == 'precipitation' else sum(numbers) / 24

def definitions(environment: str) -> dict:
    return {key: {**FEATURES[key], 'aggregation': 'daily sum' if key == 'precipitation' else 'daily mean'}
            for key in ENVIRONMENTS[environment]}
