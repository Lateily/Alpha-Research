"""Registered, closed-daily candidate replay; no orders or human approval."""
import argparse
from datetime import datetime
from decimal import Context, Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/llm'))
import foundation_materials as materials
import research_content as content
import research_artifact_io as artifacts
import workbench_backup as backup
import workbench_evidence as ev

from . import technical_contract as inputs
from .evidence import canonical, sha
from .smc_ict_concepts import confirmed_pivots
from .smc_ict_input import Bar
from .technical_profiles import PROFILE_ID, load_profile

TICK = Decimal('0.01')


def _execution_identity():
    base = content._execution_identity()
    root = Path(__file__).resolve().parent
    hashes = {name: ev.sha(ev.read_local(root, name)) for name in ('daily_strategy.py', 'technical_contract.py', 'technical_profiles.py')}
    helper = ev.sha(ev.read_local(Path(content.__file__).resolve().parent, 'research_artifact_io.py'))
    return {**base, 'source_tree_hash': ev.sealed({'base': base['source_tree_hash'], 'daily': hashes, 'artifact_io':helper})}


def wilder_at(bars, index, period=14):
    if index + 1 < period:
        return None
    with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN)):
        ranges = []
        for pos, row in enumerate(bars[:index + 1]):
            high, low = Decimal(row['high']), Decimal(row['low'])
            prior = Decimal(bars[pos - 1]['close']) if pos else None
            ranges.append(max(high - low, abs(high - prior), abs(low - prior)) if prior is not None else high - low)
        value = sum(ranges[:period]) / period
        # governance-mutation: DAILY_STRATEGY_WILDER
        for current in ranges[period:]:
            value = (value * (period - 1) + current) / period
        return value


def _snapshot(registry_path, registry_hash, pack_id):
    inputs._hash(registry_hash); inputs._identifier(pack_id)
    raw = inputs._read(Path(registry_path), [0])
    # governance-mutation: DAILY_STRATEGY_REGISTRY_PIN
    if sha(raw) != registry_hash:
        inputs._fail('REGISTRY_PIN')
    roots, _packs = inputs._inspection_config(raw)
    registry = inputs._json(raw)
    if pack_id not in registry['packs']:
        inputs._fail('UNKNOWN_PACK')
    binding = registry['packs'][pack_id]
    result = inputs.validate_pack(Path(binding['pack_root']), binding, roots, load_profile(PROFILE_ID))
    if result['request'] is not None and result['request']['pack_id'] != pack_id:
        inputs._fail('REGISTRY_PACK_ID_MISMATCH')
    return result


def _captured_snapshot(registry_path, registry_hash, pack_id):
    captured = {}
    token = inputs._CAPTURE.set(captured)
    try:
        result = _snapshot(registry_path, registry_hash, pack_id)
    finally:
        inputs._CAPTURE.reset(token)
    return result, captured


class _EventEvidence(inputs._FrozenEvidence):
    def bytes(self, ref):
        inputs._ref(ref, [])
        key = ref['root_alias'] + ':' + ref['path']
        # A missing file cannot appear later and silently join the event view.
        if key not in self.raw:
            return None
        return super().bytes(ref)


def _event_evidence(validated, captured, registry_path):
    raw = captured[inputs._absolute(Path(registry_path))][0]
    roots, _ = inputs._inspection_config(raw)
    evidence = {}
    hashes = dict(validated['bindings']['evidence_byte_hashes'])
    for key, pin in hashes.items():
        alias, name = key.split(':', 1)
        saved = captured.get(roots[alias] / name)
        if saved is None or sha(saved[0]) != pin:
            inputs._fail('EVENT_SOURCE_CHANGED')
        evidence[key] = saved[0]
    return _EventEvidence(roots, [0], evidence, hashes)


def _render(number):
    if number is None:
        return None
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _points(rows):
    bars = tuple(Bar(datetime.fromisoformat(x['bar_close_at']),
                     *(Decimal(x[k]) for k in ('open', 'high', 'low', 'close')),
                     int(Decimal(x['volume'])), (x['trade_date'],)) for x in rows)
    points = confirmed_pivots(bars, 2, 2)
    for group in points.values():
        for point in group:
            index = point['index']; confirmed = rows[index + 2]['bar_close_at']
            available = max(datetime.fromisoformat(x['available_at']) for x in rows[index-2:index+3])
            point.update(confirmed_at=confirmed, available_at=available.isoformat(),
                         known_at=max(datetime.fromisoformat(confirmed), available).isoformat())
    return bars, points


def _first_event(bars, points):
    with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN)):
        return _first_event_exact(bars, points)


def _first_event_exact(bars, points):
    for index in range(1, len(bars)):
        prior = bars[index - 1].end
        known = [p for p in points['LOW'] if datetime.fromisoformat(p['known_at']) <= prior]
        if not known:
            continue
        ref = known[-1]; level = Decimal(ref['price']); confirmation = ref['index'] + 2
        # governance-mutation: DAILY_STRATEGY_FIRST_REFERENCE
        if any(bar.low < level for bar in bars[confirmation + 1:index]):
            continue
        if bars[index].low > level - TICK:
            continue
        reclaim = next((j for j in range(index, min(index + 4, len(bars))) if bars[j].close >= level), None)
        return ref, index, reclaim
    return None


def _levels(rows, bars, points, sweep, reclaim):
    atr = wilder_at(rows, reclaim)
    if atr is None:
        return None
    with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN)):
        entry = ((bars[reclaim].high + TICK) / TICK).to_integral_value(rounding=ROUND_CEILING) * TICK
        stop = ((bars[sweep].low - Decimal('0.25') * atr) / TICK).to_integral_value(rounding=ROUND_FLOOR) * TICK
        targets = []
        for point in points['HIGH']:
            # governance-mutation: DAILY_STRATEGY_TARGET_PIT
            if datetime.fromisoformat(point['known_at']) >= bars[reclaim].end:
                continue
            price = Decimal(point['price'])
            if price > entry and not any(x.high >= price for x in bars[point['index'] + 3:reclaim + 1]):
                targets.append((price, point))
        unique = {}
        for price, point in sorted(targets, key=lambda x: x[0]):
            unique.setdefault(price, point)
        prices = sorted(unique)
        target1, target2 = (prices[0] if prices else None), (prices[1] if len(prices) > 1 else None)
        risk = entry - stop
        rr = ((target1 - entry) / risk).quantize(Decimal('0.00000001')) if target1 is not None and risk > 0 and stop > 0 else None
        return {'entry_reference': _render(entry), 'structure_invalidation': _render(bars[sweep].low),
                'stop_reference': _render(stop), 'target_1': _render(target1), 'target_2': _render(target2),
                'atr14_wilder': _render(atr), 'tick': '0.01', 'stop_atr_multiplier': '0.25',
                'target_sources': [unique[x] for x in prices[:2]], 'gross_rr': _render(rr),
                'after_cost_rr': None, 'cost_status': 'DATA_BLOCKED',
                'source_bar_dates': {'entry': rows[reclaim]['trade_date'], 'stop': rows[sweep]['trade_date']},
                'scope': 'UNAPPROVED_RESEARCH_REFERENCES_NOT_ORDERS'}


def _lifecycle(rows, bars, sweep, reclaim, levels):
    seen = {'entry_trigger_seen_at': None, 'target_seen_at': None,
            'structure_invalidated_at': None, 'stop_reference_touch_seen_at': None}
    ambiguous = []
    if levels is None:
        return seen, ambiguous
    entry, stop = Decimal(levels['entry_reference']), Decimal(levels['stop_reference'])
    target = Decimal(levels['target_1']) if levels['target_1'] is not None else None
    for i in range(reclaim + 1, len(bars)):
        day, bar = rows[i]['trade_date'], bars[i]
        tests = {'entry_trigger_seen_at': bar.high >= entry,
                 'target_seen_at': target is not None and bar.high >= target,
                 'structure_invalidated_at': bar.close < bars[sweep].low,
                 'stop_reference_touch_seen_at': bar.low <= stop}
        for key, touched in tests.items():
            if touched and seen[key] is None:
                seen[key] = day
        if (tests['entry_trigger_seen_at'] or tests['target_seen_at']) and (tests['structure_invalidated_at'] or tests['stop_reference_touch_seen_at']):
            ambiguous.append(day)
    return seen, ambiguous


def _event_history_gaps(validated, rows, reclaim):
    cutoff = datetime.fromisoformat(rows[reclaim]['bar_close_at'])
    late = [row['trade_date'] for row in rows[:reclaim + 1] if datetime.fromisoformat(row['available_at']) > cutoff]
    late_roles = [source['role'] for source in validated['source_manifest']['sources']
                  if source['role'] in {'bars', 'calendar', 'corporate_actions'} and any(
                      datetime.fromisoformat(source[key]) > cutoff for key in ('published_at', 'available_at'))]
    return {'bar_dates': late, 'source_roles': late_roles}


def _event_context(validated, rows, reclaim, evidence, history_gaps):
    observed = rows[:reclaim + 1]
    event_time = rows[reclaim]['bar_close_at']
    request = dict(validated['request'], as_of=event_time, data_cutoff=event_time)
    quality = {'roles': {role: {'reason_codes': []} for role in ('context', 'flow', 'research_binding')}}
    reasons = []
    def block(role, code):
        reasons.append(code)
        if code not in quality['roles'][role]['reason_codes']:
            quality['roles'][role]['reason_codes'].append(code)
    inputs._context(validated['inputs']['context'], request, evidence, {}, quality, block)
    rb = validated['inputs']['research_binding']
    if rb is not None:
        inputs._red_flags(request, rb['red_flags'], evidence, quality, block)
    else:
        quality['red_flags'] = {'status': 'UNKNOWN', 'source_refs': []}
        block('research_binding', 'RED_FLAG_COVERAGE_UNKNOWN')
    history_missing = bool(history_gaps['bar_dates'] or history_gaps['source_roles'])
    calendar_reasons = ['EVENT_INPUT_AFTER_CUTOFF'] if history_missing else []
    inputs._flow(validated['inputs']['flow'], request, [row['trade_date'] for row in observed], calendar_reasons, quality, block)
    for source in validated['source_manifest']['sources']:
        role = source['role']
        if role in quality['roles'] and any(datetime.fromisoformat(source[key]) > datetime.fromisoformat(event_time)
                                            for key in ('published_at', 'available_at')):
            block(role, 'EVENT_SOURCE_AFTER_CUTOFF')
            if role == 'context':
                quality['context']['status'] = 'DATA_BLOCKED'
                quality['context']['reason_codes'].append('EVENT_SOURCE_AFTER_CUTOFF')
            elif role == 'flow':
                quality['flow'].update(status='DATA_BLOCKED', last_two_sum=None, missing_reason='EVENT_SOURCE_AFTER_CUTOFF')
            else:
                quality['red_flags']['status'] = 'UNKNOWN'
    volume = None
    # governance-mutation: DAILY_EVENT_VOLUME_PRECISION
    with localcontext(Context(prec=200, rounding=ROUND_HALF_EVEN)):
        if not history_missing and len(observed) >= 60:
            volume = sum(Decimal(x['volume']) for x in observed[-5:]) * 12 >= sum(Decimal(x['volume']) for x in observed[-60:])
    dates = [x['trade_date'] for x in observed[-2:]]
    total = Decimal(quality['flow']['last_two_sum']) if quality['flow']['last_two_sum'] is not None else None
    at_event = quality['context']['status'] == 'CONFIRMED'
    return {'volume_5_mean_gte_60_mean': volume, 'settled_flow_dates': dates,
            'settled_flow_sum': _render(total), 'settled_flow_positive': total > 0 if total is not None else None,
            'context_known_at_event': at_event, 'context_validation': quality['context'],
            'red_flags': quality['red_flags'], 'event_information_cutoff': event_time,
            'event_source_reason_codes': sorted(set(reasons)), 'history_gaps': history_gaps,
            'validation_scope': 'DERIVED_EVENT_VIEW_FROM_PINNED_SOURCES_NOT_NEW_AUTHORITY'}


def evaluate(registry_path, registry_hash, pack_id):
    validated, captured = _captured_snapshot(registry_path, registry_hash, pack_id)
    request = validated['request']; profile = load_profile(PROFILE_ID)
    result = {'schema': 'ar.daily-strategy-card.v1', 'profile_id': PROFILE_ID,
              'profile_hash': profile['profile_hash'], 'spec_byte_sha256': profile['spec_byte_sha256'],
              'request': request, 'bindings': validated['bindings'], 'quality': validated['quality'],
              'status': validated['status'], 'reason_codes': list(validated['reason_codes']),
              'structure': None, 'setup': None, 'levels': None, 'context': None, 'lifecycle': None,
              'human_review': {'status': 'PENDING', 'reviewer': None},
              'source_authenticity': 'UNVERIFIED', 'financial_or_method_efficacy': 'UNVERIFIED',
              'registration_readiness': 'NOT_AUTHORIZED', 'authority': validated['authority']}
    # governance-mutation: DAILY_STRATEGY_STRUCTURAL_GATE
    if validated['quality']['structural_input_status'] != 'STRUCTURALLY_VALID':
        return result
    rows = validated['inputs']['bars']['rows']; bars, points = _points(rows)
    result['structure'] = {'pivots': points, 'implemented_methods': ['STRICT_PIVOT_LOW', 'STRICT_PIVOT_HIGH', 'LIQUIDITY_SWEEP', 'RECLAIM'],
                           'unimplemented_concepts': [x['method_id'] for x in profile['method_catalog'] if not x['enabled']]}
    event = _first_event(bars, points)
    if event is None:
        result.update(status='NO_SETUP', reason_codes=sorted(set(result['reason_codes'] + ['NO_LEGAL_SWEEP'])))
        return result
    ref, sweep, reclaim = event
    result['setup'] = {'reference': ref, 'sweep_date': rows[sweep]['trade_date'],
                       'reclaim_date': rows[reclaim]['trade_date'] if reclaim is not None else None,
                       'event_selection': 'FIRST_LEGAL_EVENT', 'sweep_source': {'index': sweep, 'bar': rows[sweep]},
                       'reclaim_source': {'index': reclaim, 'bar': rows[reclaim]} if reclaim is not None else None}
    if reclaim is None:
        waiting = len(rows) - 1 < sweep + 3
        result.update(status='WAIT' if waiting else 'NO_SETUP',
                      reason_codes=sorted(set(result['reason_codes'] + ['RECLAIM_PENDING' if waiting else 'RECLAIM_EXPIRED'])))
        return result
    gaps = _event_history_gaps(validated, rows, reclaim)
    history_missing = bool(gaps['bar_dates'] or gaps['source_roles'])
    # governance-mutation: DAILY_EVENT_HISTORY_PIT
    levels = result['levels'] = None if history_missing else _levels(rows, bars, points, sweep, reclaim)
    lifecycle, ambiguous = _lifecycle(rows, bars, sweep, reclaim, levels)
    result['lifecycle'] = lifecycle
    evidence = _event_evidence(validated, captured, registry_path)
    result['context'] = _event_context(validated, rows, reclaim, evidence, gaps)
    reasons = list(result['reason_codes']) + ['COST_MODEL_NOT_SUPPLIED']
    if history_missing:
        reasons.append('EVENT_INPUT_AFTER_CUTOFF')
    elif levels is None:
        reasons.append('ATR_HISTORY_INSUFFICIENT')
    elif levels['target_1'] is None:
        reasons.append('TARGET_MISSING')
    elif levels['gross_rr'] is None or Decimal(levels['gross_rr']) < 2:
        reasons.append('GROSS_RR_BELOW_TWO')
    if result['context']['volume_5_mean_gte_60_mean'] is not True:
        reasons.append('VOLUME_NOT_CONFIRMED')
    if result['context']['settled_flow_positive'] is not True:
        reasons.append('SETTLED_FLOW_NOT_CONFIRMED_AT_EVENT')
    if result['context']['context_known_at_event'] is not True:
        reasons.append('CONTEXT_NOT_EVENT_TIME')
    if lifecycle['entry_trigger_seen_at'] is not None: reasons.append('ENTRY_ALREADY_TRIGGERED_BEFORE_PLAN')
    if lifecycle['target_seen_at'] is not None: reasons.append('TARGET_ALREADY_REACHED_BEFORE_PLAN')
    if ambiguous: reasons.append('INTRABAR_ORDER_UNKNOWN')
    result.update(status='DATA_BLOCKED' if history_missing else 'INVALIDATED' if lifecycle['structure_invalidated_at'] is not None else 'WAIT',
                  reason_codes=sorted(set(reasons)))
    return result


def _artifacts(registry_path, registry_hash, pack_id):
    card = evaluate(registry_path, registry_hash, pack_id)
    source = _snapshot(registry_path, registry_hash, pack_id)
    if card['bindings'] != source['bindings'] or card['request'] != source['request']:
        inputs._fail('STRATEGY_SOURCE_CHANGED')
    chart = {'schema': 'ar.daily-chart-annotations.v1', 'status': card['status'],
             'bars': (source['inputs'].get('bars') or {}).get('rows', []),
             'structure': card['structure'], 'setup': card['setup'], 'levels': card['levels'],
             'lifecycle': card['lifecycle'], 'warning': 'Raw input and candidate references, not a minute path or execution.',
             'authority': card['authority']}
    template = {'schema': 'ar.daily-human-review-template.v1', 'strategy_card_sha256': sha(canonical(card)),
                'status': 'PENDING', 'reviewer': None, 'reviewed_at': None, 'signature': None,
                'formal_approval': False}
    report = ('# Daily Technical Research Draft\n\nWORKFLOW_DEBUG; no orders; human PENDING.\n\n'
              + content.text({'identity': card['request'], 'status': card['status'],
                              'setup': card['setup'], 'levels': card['levels'], 'lifecycle': card['lifecycle'],
                              'context': card['context'], 'reason_codes': card['reason_codes']})
              + '\n\nNot a trading instruction; research signal, human executes.\n').encode()
    return {'strategy-card.json': canonical(card), 'chart-annotations.json': canonical(chart),
            'human-review-template.json': canonical(template), 'technical-report.md': report}


def create(registry_path, registry_hash, pack_id, output_root):
    output = materials._root(output_root)
    raw = inputs._read(Path(registry_path), [0]); roots, packs = inputs._inspection_config(raw)
    registry = materials._root(registry_path)
    if output == registry or output in registry.parents:
        inputs._fail('STRATEGY_ROOT_OVERLAP')
    for path in (*roots.values(), *packs):
        source = materials._root(path)
        if output == source or output in source.parents or source in output.parents:
            inputs._fail('STRATEGY_ROOT_OVERLAP')
    identity = _execution_identity()
    files = _artifacts(registry_path, registry_hash, pack_id)
    manifest = {'schema': 'ar.daily-strategy-manifest.v1', 'registry_sha256': registry_hash,
                'pack_id': pack_id, 'execution_identity': identity,
                'files': {key: sha(value) for key, value in files.items()}, **content.LABELS}
    manifest['strategy_hash'] = sha(canonical(manifest))
    encoded = canonical(manifest)
    if _execution_identity() != identity:
        inputs._fail('STRATEGY_CODE_CHANGED')
    if any(len(value) > ev.MAX_FILE for value in (*files.values(), encoded)):
        inputs._fail('STRATEGY_OUTPUT_SIZE')
    return artifacts.publish(output, files, 'strategy-manifest.json', encoded,
        lambda: verify(output, manifest['strategy_hash'], registry_path, registry_hash, pack_id))


def verify(output_root, strategy_hash, registry_path, registry_hash, pack_id):
    with artifacts.read(output_root, {'strategy-card.json', 'chart-annotations.json',
            'human-review-template.json', 'technical-report.md', 'strategy-manifest.json'}) as raw:
        return _verify(raw, strategy_hash, registry_path, registry_hash, pack_id)


def _verify(saved, strategy_hash, registry_path, registry_hash, pack_id):
    inputs._hash(strategy_hash)
    marker = ev.parse(saved['strategy-manifest.json'])
    materials._exact(marker, {'schema', 'registry_sha256', 'pack_id', 'execution_identity',
                             'files', 'strategy_hash', *content.LABELS})
    if (marker['schema'] != 'ar.daily-strategy-manifest.v1' or marker['strategy_hash'] != strategy_hash
            or sha(canonical({k:v for k,v in marker.items() if k != 'strategy_hash'})) != strategy_hash
            or marker['registry_sha256'] != registry_hash or marker['pack_id'] != pack_id
            or any(type(marker[k]) is not type(v) or marker[k] != v for k,v in content.LABELS.items())):
        inputs._fail('STRATEGY_MANIFEST_PIN')
    files = _artifacts(registry_path, registry_hash, pack_id)
    materials._exact(marker['files'], set(files))
    materials._exact(marker['execution_identity'], {'code_sha', 'source_tree_hash'})
    materials._hash(marker['execution_identity']['code_sha'], 40)
    materials._hash(marker['execution_identity']['source_tree_hash'])
    # governance-mutation: DAILY_STRATEGY_DERIVATION
    if any(saved[name] != raw or marker['files'][name] != sha(raw) for name,raw in files.items()):
        inputs._fail('STRATEGY_DERIVATION')
    card = ev.parse(files['strategy-card.json'])
    return {'schema': 'ar.daily-strategy-receipt.v1', 'strategy_hash': strategy_hash,
            'registry_sha256': registry_hash, 'pack_id': pack_id, 'status': card['status'],
            'report_sha256': marker['files']['technical-report.md'], **content.LABELS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('create', 'verify'))
    for key in ('registry', 'registry-hash', 'pack-id', 'output'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--strategy-hash')
    args = parser.parse_args()
    values = (Path(args.registry), args.registry_hash, args.pack_id)
    if args.command == 'create':
        result = create(*values, Path(args.output))
    else:
        if args.strategy_hash is None: parser.error('strategy hash required')
        result = verify(Path(args.output), args.strategy_hash, *values)
    print(ev.canonical(result))


if __name__ == '__main__':
    main()
