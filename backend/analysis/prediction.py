"""Single-species seasonal profiles, environmental outlooks, and day comparison."""
import asyncio
import copy
from datetime import date, timedelta
from cachetools import TTLCache
from analysis.data_ingestion import local_occurrences, align_history, environmental_days, timestamp
from analysis.features import definitions, ENVIRONMENTS
from analysis.geo import background_samples
from analysis.probability_model import train_model, predict, evidence_eligibility
from analysis.interpretation import generate_interpretation
from config import MODEL_VERSION

model_cache = TTLCache(maxsize=24, ttl=3600)


def historical_profile(records):
    return [{'month': month, 'count': sum(r['month'] == month for r in records),
             'years': sorted({int(r['date'][:4]) for r in records if r['month'] == month})}
            for month in range(1, 13)]


async def collect_local(request, progress):
    radius = request.radius_km
    while True:
        progress(f'Fetching local sightings within {radius:g} km…')
        records, completeness = await local_occurrences(request.taxon_id, request.target_lat,
            request.target_lng, radius, request.limit, progress)
        if len(records) >= 50 or radius >= 50:
            return records, radius, completeness
        radius = min(radius + 5, 50)


def base_result(request, records, radius, completeness):
    dates = sorted(r['date'] for r in records)
    return {'type': 'historical_profile', 'species': {'id': request.taxon_id, 'name': request.species},
            'environment': request.environment, 'target_date': str(request.target_date),
            'location': {'lat': request.target_lat, 'lng': request.target_lng},
            'profile': historical_profile(records), 'features': definitions(request.environment),
            'evidence': {'sightings': len(records), 'background_samples': 0, 'excluded_records': [],
                         'eligibility': evidence_eligibility(),
                         'date_start': dates[0] if dates else None, 'date_end': dates[-1] if dates else None,
                         'radius_km': radius, 'record_ids': [r['id'] for r in records],
                         'source_records': [{'id': r['id'], 'date': r['date']} for r in records],
                         'completeness': completeness, 'fetched_at': timestamp(), 'seed': 42,
                         'model_version': MODEL_VERSION},
            'warnings': ['Recorded sightings reflect observer effort, not confirmed encounter rates.']}


async def training(request, progress):
    records, radius, completeness = await collect_local(request, progress)
    result = base_result(request, records, radius, completeness)
    if not completeness['complete']:
        result['warnings'].append('Sightings are a capped local sample; monthly counts are not complete totals.')
    if not records:
        result['summary'] = 'No matching recorded sightings were found. This does not mean the species is absent.'
        return None, result
    if request.method == 'rustic':
        result['summary'] = 'This chart shows when local sightings were recorded across years. It does not estimate the chance of a successful visit.'
        return None, result
    max_day = date.today() + timedelta(days=9 if request.environment == 'marine' else 6)
    if request.operation == 'single_day' and request.method == 'glm' and not date.today() <= request.target_date <= max_day:
        result['weather'] = {'available': False, 'reason': 'Date is outside the supported forecast window.'}
        result['summary'] = 'Weather is unavailable for this date. Use the historical monthly sightings profile as a seasonal reference.'
        return None, result
    progress('Generating reproducible background samples inside the study circle…')
    backgrounds = background_samples(records, request.target_lat, request.target_lng, radius)
    aligned, excluded = await align_history(records + backgrounds, request.environment, progress,
                                            retain_partial=request.method == 'rf')
    result['evidence'].update({'background_samples': len(backgrounds), 'excluded_records': excluded,
        'usable_sightings': sum(p['presence'] == 1 for p in aligned),
        'usable_background': sum(p['presence'] == 0 for p in aligned),
        'training_records': [{'id': p['id'], 'date': p['date']} for p in aligned]})
    result['evidence']['eligibility'] = evidence_eligibility(aligned, 'aligned', final=request.method != 'rf')
    progress('Validating spatial and chronological holdouts against the seasonal baseline…')
    try:
        model, metadata = await asyncio.to_thread(train_model, aligned, request.environment, request.method)
    except ValueError as exc:
        result['evidence']['eligibility'] = getattr(exc, 'eligibility', result['evidence']['eligibility'])
        if getattr(exc, 'validation', None) is not None:
            result['evidence']['validation'] = exc.validation
        if request.method == 'rf':
            result['evidence']['excluded_records'].extend(getattr(exc, 'exclusions', []))
            for key in ('usable_sightings', 'usable_background', 'training_records'):
                result['evidence'].pop(key, None)
        result['summary'] = str(exc)
        result['warnings'].append('Environmental model unavailable; the historical profile remains available.')
        return None, result
    result['model'] = metadata
    result['evidence']['eligibility'] = metadata['eligibility']
    if request.method == 'rf':
        imputation = metadata['imputation']
        retained = metadata['training_records']
        result['evidence'].update({key: imputation[key] for key in
                                  ('complete_records', 'imputed_records', 'observed_cells', 'imputed_cells')})
        result['evidence']['excluded_records'].extend(imputation['exclusions'])
        result['evidence'].update(usable_sightings=sum(r['presence'] == 1 for r in retained),
                                  usable_background=sum(r['presence'] == 0 for r in retained),
                                  training_records=[{'id': r['id'], 'date': r['date']} for r in retained])
        if imputation['imputed_records']:
            result['warnings'].append(
                f"Key Factors includes {imputation['imputed_cells']} estimated environmental values across "
                f"{imputation['imputed_records']} records. Proximity imputation does not eliminate missingness bias.")
    result['type'] = 'environmental_outlook'
    if metadata['validation']['experimental']:
        unavailable = [name for name in ('spatial', 'chronological') if not metadata['validation'][name]]
        result['warnings'].append('Experimental: independent validation unavailable for ' + ', '.join(unavailable) + '.')
    if not metadata['validation']['ranking_allowed']:
        result['warnings'].append(
            'Validation has not demonstrated improvement over the seasonal baseline in both holdouts; feature importance remains available as descriptive associations, without established predictive skill.'
            if request.method == 'rf' else
            'Validation has not demonstrated improvement over the seasonal baseline in both holdouts; favorability assessments and day rankings are withheld.')
    return model, result


def ranking_allowed(model_metadata, days):
    eligible = model_metadata['validation']['ranking_allowed']
    usable = [d for d in days if d.get('available') and not d.get('extrapolated_variables')]
    return eligible and len(usable) >= 2


async def future_days(request, model, result, progress):
    today = date.today()
    start = today if request.operation == 'compare_days' else request.target_date
    end = start + timedelta(days=6) if request.operation == 'compare_days' else start
    # Common conservative horizon: marine SST/currents are supported for up to ten days.
    max_day = today + timedelta(days=9 if request.environment == 'marine' else 6)
    if start < today or start > max_day:
        result['type'] = 'historical_profile'
        result['weather'] = {'available': False, 'reason': 'Date is outside the supported forecast window.'}
        result['summary'] = 'Weather is unavailable for this date. Use the historical monthly sightings profile as a seasonal reference.'
        return
    end = min(end, max_day)
    progress('Fetching the same daily environmental measures used during training…')
    conditions, warnings = await environmental_days(request.target_lat, request.target_lng,
        start, end, request.environment, forecast=True)
    result['warnings'].extend(warnings)
    days = []
    for day, values in conditions.items():
        forecast = predict(model, result['model'], values, day)
        days.append({'date': day, 'conditions': values, 'provenance': 'forecast', **forecast})
    result['days'] = days
    if request.operation == 'compare_days':
        result['type'] = 'day_comparison'
        if ranking_allowed(result['model'], days):
            usable = [d for d in days if d.get('available') and not d.get('extrapolated_variables')]
            ranked = sorted(usable, key=lambda d: (-d['relative_score'], d['date']))
            # A tie is not evidence that one day is better.
            if max(d['relative_score'] for d in ranked) - min(d['relative_score'] for d in ranked) > 1e-6:
                for rank, day in enumerate(ranked, 1):
                    day['rank'] = rank
                best = date.fromisoformat(ranked[0]['date']).strftime('%A, %B %d')
                result['summary'] = f'{best} has the most favorable modeled conditions among the supported days. This is a relative comparison, not an encounter probability.'
                return
        result['summary'] = 'A reliable day ranking is unavailable: validation must beat the seasonal baseline in both holdouts, with at least two dates inside the training range. The supported conditions are shown below.'
    else:
        result['summary'] = 'The forecast is available, but validation does not support a reliable favorability assessment. Conditions and historical sightings are shown as evidence, not encounter chances.'
        if not days[0]['available']:
            result['summary'] = 'Required forecast data is missing. An environmental outlook is unavailable; the historical profile remains available.'
        elif days[0]['extrapolated_variables']:
            result['warnings'].append('Some forecast values fall outside the training range; an outlook would extrapolate beyond the evidence.')
            result['summary'] = 'Forecast conditions extend outside the local training range. A reliable favorability assessment is unavailable.'
        elif result['model']['validation']['ranking_allowed']:
            low, high = result['model']['reference_quartiles']
            score = days[0]['relative_score']
            description = 'more favorable' if score >= high else 'less favorable' if score <= low else 'typical'
            result['summary'] = f'Conditions look {description} compared with the conditions in this model’s local training sample. This comparison does not establish the chance of seeing the animal.'


async def run_analysis(request, progress, api_key=None):
    key = (MODEL_VERSION, request.taxon_id, request.target_lat, request.target_lng, request.radius_km,
           request.limit, request.environment, request.method, str(date.today()))
    if key in model_cache:
        model, cached = model_cache[key]
        result = copy.deepcopy(cached)
        result['target_date'] = str(request.target_date)
    else:
        model, result = await training(request, progress)
        if model is not None:
            cached_result = copy.deepcopy(result)
            cached_result.pop('target_date', None)
            model_cache[key] = (model, cached_result)
    if model is not None:
        if request.method == 'rf' and request.operation == 'single_day':
            result['summary'] = 'These are modeled associations with recorded sightings, not proof of ecological causes. Importance is shown below; this mode does not forecast an encounter.'
        else:
            await future_days(request, model, result, progress)
    result.setdefault('summary', 'Insufficient evidence for an environmental outlook.')
    progress('Preparing the evidence summary…')
    # Do not send exact coordinates or source records to the optional AI service.
    ai_evidence = {k: result[k] for k in ('type', 'summary', 'warnings')}
    metadata = result.get('model')
    if metadata:
        # Imputation diagnostics contain per-record provenance; keep those out of AI requests.
        ai_model = {k: metadata[k] for k in ('model_type', 'features', 'variable_importance', 'n_records')}
        validation = metadata['validation']
        ai_model['validation'] = {k: validation[k] for k in ('experimental', 'ranking_allowed', 'unavailable_reasons')}
        for split in ('spatial', 'chronological'):
            item = validation[split]
            ai_model['validation'][split] = ({k: v for k, v in item.items() if k != 'imputation'} if item else None)
        if 'imputation' in metadata:
            ai_model['imputation'] = {k: metadata['imputation'][k] for k in
                ('method', 'version', 'parameters', 'donor_counts', 'complete_records',
                 'imputed_records', 'observed_cells', 'imputed_cells')}
        ai_evidence['model'] = ai_model
    else:
        ai_evidence['model'] = None
    result['interpretation'] = await asyncio.to_thread(generate_interpretation,
        request.species, ai_evidence, result['summary'], api_key)
    return result
