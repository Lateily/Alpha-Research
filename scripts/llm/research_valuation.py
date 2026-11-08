"""Typed financial reconciliations; reported anchors are not normal earnings."""
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from datetime import datetime, time, timedelta, timezone
import re

import foundation_materials as materials
import foundation_research as material
import workbench_evidence as ev

CASH_COMPONENTS = {'cash', 'restricted_cash', 'short_term_debt', 'long_term_debt',
                   'current_debt_and_lease', 'lease_debt', 'other_interest_debt', 'period_end_shares'}


def _fail(reason):
    raise ev.EvidenceError('VALUATION_BASIS_' + reason)


def _render(value):
    rendered = format(value, 'f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def evaluate(value, facts, *, read=None, company=None, generated_at=None):
    # Facts are the numeric/quote-verified map from research_content, not claims
    # accepted directly from an untrusted request. Semantic mappings remain E3.
    from research_content import _number
    v2 = type(value) is dict and value.get('schema') == 'ar.valuation-basis.v2'
    materials._exact(value, {'schema', 'period', 'nonrecurring', 'anchors', 'cash_inventory'} |
                     ({'earnings_history', 'cash_disclosures', 'multiple_observation'} if v2 else set()))
    if value['schema'] not in ('ar.valuation-basis.v1', 'ar.valuation-basis.v2') or not re.fullmatch(r'\d{4}(FY|H1|Q[1-4])', value['period']):
        _fail('SCHEMA_OR_PERIOD')

    def fact(key, unit, period):
        if type(key) is not str or key not in facts:
            _fail('REFERENCE')
        row = facts[key]
        # governance-mutation: VALUATION_BASIS_TYPES
        if row['unit'] != unit or row['period'] != period:
            _fail('UNIT_OR_PERIOD')
        return _number(row['value'])

    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        bridge = value['nonrecurring']
        materials._exact(bridge, {'profit', 'ex_profit', 'total', 'pretax_items', 'tax', 'minority', 'coverage_note'})
        material._string(bridge['coverage_note'], 2000)
        items = bridge['pretax_items']
        if type(items) is not list or not 1 <= len(items) <= 32:
            _fail('BRIDGE_ITEMS')
        references = [bridge[key] for key in ('profit', 'ex_profit', 'total', 'tax', 'minority')]
        pretax = Decimal(0)
        for item in items:
            materials._exact(item, {'fact_id', 'sign'})
            if type(item['sign']) is not int or item['sign'] not in (-1, 1):
                _fail('BRIDGE_SIGN')
            references.append(item['fact_id'])
            pretax += item['sign'] * fact(item['fact_id'], 'CNY', value['period'])
        if any(type(ref) is not str for ref in references) or len(set(references)) != len(references):
            _fail('DUPLICATE_REFERENCE')
        profit, ex_profit, total, tax, minority = [fact(bridge[key], 'CNY', value['period'])
                                                  for key in ('profit', 'ex_profit', 'total', 'tax', 'minority')]
        after_tax = pretax - tax - minority
        # governance-mutation: VALUATION_BRIDGE_RECONCILIATION
        matched = after_tax == total == profit - ex_profit
        reconciliation = {**bridge, 'status': 'ARITHMETIC_RECONCILED_SEMANTICS_UNVERIFIED' if matched else 'DATA_BLOCKED',
                          'pretax_calculated': _render(pretax), 'after_tax_calculated': _render(after_tax),
                          'declared_total': _render(total), 'profit_minus_ex_profit': _render(profit - ex_profit)}
        anchors = value['anchors']
        materials._exact(anchors, {'reported_eps', 'ex_nonrecurring_eps', 'operating_cashflow'})
        anchor_result = {}
        for key, ref in anchors.items():
            number = fact(ref, 'CNY' if key == 'operating_cashflow' else 'CNY_PER_SHARE', value['period']) if ref is not None else None
            anchor_result[key] = None if number is None else {'fact_id': ref, 'value': _render(number)}
        ex_eps = anchor_result['ex_nonrecurring_eps']
        anchor_result['half_year_ex_eps_x2_sensitivity'] = (
            _render(Decimal(ex_eps['value']) * 2) if value['period'].endswith('H1') and ex_eps else None)
        anchor_result['status'] = 'REPORTED_ANCHORS_NOT_NORMALIZED_EPS_OR_FORECAST'
        cash = value['cash_inventory']
        if cash is None:
            cash_result = {'status': 'DATA_BLOCKED', 'missing_components': sorted(CASH_COMPONENTS),
                           'net_cash': None, 'net_cash_per_share': None}
        else:
            materials._exact(cash, {'period', 'components'})
            materials._date(cash['period'])
            expected = value['period'][:4] + {'H1': '0630', 'FY': '1231', 'Q1': '0331', 'Q2': '0630', 'Q3': '0930', 'Q4': '1231'}[value['period'][4:]]
            if cash['period'] != expected:
                _fail('BALANCE_DATE')
            materials._exact(cash['components'], CASH_COMPONENTS)
            observed = {key: fact(ref, 'COUNT' if key == 'period_end_shares' else 'CNY', cash['period'])
                        for key, ref in cash['components'].items() if ref is not None}
            refs = [ref for ref in cash['components'].values() if ref is not None]
            if len(refs) != len(set(refs)) or any(number < 0 for number in observed.values()):
                _fail('CASH_INVENTORY')
            shares = observed.get('period_end_shares')
            if shares is not None and (shares <= 0 or shares != int(shares)):
                _fail('SHARE_DENOMINATOR')
            missing = sorted(CASH_COMPONENTS - observed.keys())
            net = per_share = None
            # governance-mutation: VALUATION_CASH_COVERAGE
            if not missing:
                net = observed['cash'] - sum(observed[key] for key in CASH_COMPONENTS - {'cash', 'period_end_shares'})
                per_share = (net / shares).quantize(Decimal('0.00000001'))
            cash_result = {**cash, 'status': 'DATA_BLOCKED' if missing else 'INVENTORY_ARITHMETIC_SEMANTICS_UNVERIFIED',
                           'observed_components': {key: _render(number) for key, number in observed.items()},
                           'observed_cash': _render(observed['cash']) if 'cash' in observed else None,
                           'missing_components': missing, 'net_cash': _render(net) if net is not None else None,
                           'net_cash_per_share': _render(per_share) if per_share is not None else None}
    result = {'schema': 'ar.valuation-basis-card.v2' if v2 else 'ar.valuation-basis-card.v1',
            'status': 'BASIS_PARTIAL_NORMALIZATION_PENDING' if matched else 'DATA_BLOCKED',
            'adapter': 'SEMICONDUCTOR_NORMALIZED_EARNINGS',
            'formula': 'normalized_eps * fair_multiple + net_cash_per_share',
            'nonrecurring': reconciliation, 'anchors': anchor_result, 'cash_inventory': cash_result,
            'normalized_eps': None, 'value_band': None, 'target_price': False, 'calibrated': False,
            'missing_inputs': ['Cycle-normalized revenue/margin/operating-cost assumptions', 'Normalized tax and diluted share assumptions',
                               'Excess cash versus operating cash; interest income double-counting audit',
                               'Documented comparable/history fair-multiple range', 'Source semantics and human verification'],
            'human_review': 'PENDING', 'evidence_tier': 'E3',
            'warning': 'Ex-nonrecurring profit is a reported anchor, not proof of sustainable normal earnings.'}
    if v2:
        result.update(_extended_basis(value, fact, read, company, generated_at))
    return result


HISTORY_FIELDS = {'revenue', 'ex_profit', 'reported_eps', 'ex_eps', 'operating_cashflow',
                  'pre_tax_profit', 'tax_expense', 'interest_income', 'operating_cost',
                  'selling_expense', 'admin_expense', 'rd_expense'}


def _extended_basis(value, fact, read, company, generated_at):
    rows = value['earnings_history']
    if type(rows) is not list or not 1 <= len(rows) <= 5:
        _fail('HISTORY_ROWS')
    periods, history = [], []
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        for row in rows:
            materials._exact(row, {'period', *HISTORY_FIELDS})
            period = row['period']
            # governance-mutation: VALUATION_ANNUAL_HISTORY_DATE
            if (type(period) is not str or not re.fullmatch(r'\d{4}FY', period)
                    or period[:4] > value['period'][:4]
                    or (period[:4] == value['period'][:4] and not value['period'].endswith('FY'))):
                _fail('HISTORY_PERIOD')
            periods.append(period)
            values = {key: fact(ref, 'CNY_PER_SHARE' if key in ('reported_eps', 'ex_eps') else 'CNY', period)
                      for key, ref in row.items() if key != 'period' and ref is not None}
            refs = [ref for key, ref in row.items() if key != 'period' and ref is not None]
            if len(refs) != len(set(refs)):
                _fail('HISTORY_DUPLICATE_REFERENCE')
            ratios = {}
            for name, numerator, denominator in [('ex_profit_margin_pct', 'ex_profit', 'revenue'),
                                                   ('effective_tax_pct_NOT_NORMAL_TAX', 'tax_expense', 'pre_tax_profit')]:
                n, d = values.get(numerator), values.get(denominator)
                ratios[name] = _render((100*n/d).quantize(Decimal('0.00000001'))) if n is not None and d is not None and d != 0 else None
            history.append({'period': period, 'references': {key: row[key] for key in sorted(HISTORY_FIELDS)},
                'values': {key: _render(values[key]) if key in values else None for key in sorted(HISTORY_FIELDS)},
                'missing_fields': sorted(HISTORY_FIELDS - values.keys()), 'diagnostics': ratios,
                'status': 'REPORTED_ANNUAL_ANCHORS_NOT_NORMALIZED_EARNINGS'})
    if periods != sorted(set(periods)):
        _fail('HISTORY_ORDER')
    disclosures = value['cash_disclosures']
    if type(disclosures) is not list or len(disclosures) > 16:
        _fail('DISCLOSURE_ROWS')
    bound = []
    for row in disclosures:
        materials._exact(row, {'component', 'period', 'kind', 'citation'})
        inventory = value['cash_inventory']
        if (inventory is None or row['component'] not in CASH_COMPONENTS or row['period'] != inventory['period']
                or inventory['components'][row['component']] is not None):
            _fail('DISCLOSURE_CONFLICT')
        if row['kind'] not in ('EXPLICIT_NOT_APPLICABLE', 'BLANK_CURRENT_COLUMN_UNRESOLVED', 'CLASSIFICATION_SCOPE_UNRESOLVED') or read is None:
            _fail('DISCLOSURE_KIND_OR_SOURCE')
        citation = row['citation']; materials._exact(citation, {'sha256', 'page', 'start', 'end', 'expected'})
        materials._hash(citation['sha256'])
        if any(type(citation[key]) is not int or citation[key] < 1 for key in ('page', 'start', 'end')):
            _fail('DISCLOSURE_RANGE')
        name = 'inputs/pages/' + citation['sha256'] + '-p' + str(citation['page']) + '.txt'
        lines = read(name).decode('utf-8').splitlines()
        if citation['start'] > citation['end'] or citation['end'] > len(lines):
            _fail('DISCLOSURE_RANGE')
        quote = '\n'.join(lines[citation['start']-1:citation['end']])
        # governance-mutation: VALUATION_DISCLOSURE_QUOTE
        if quote != citation['expected']:
            _fail('DISCLOSURE_QUOTE')
        if row['kind'] == 'EXPLICIT_NOT_APPLICABLE' and '\u25a1\u9002\u7528\u221a\u4e0d\u9002\u7528' not in re.sub(r'\s+', '', quote):
            _fail('DISCLOSURE_NOT_EXPLICIT')
        bound.append({**row, 'status': 'QUOTE_VERIFIED_SEMANTICS_AND_COLUMN_INTERPRETATION_PENDING',
                      'numeric_zero_inferred': False, 'human_review': 'PENDING'})
    return {'earnings_history': history, 'cash_disclosures': bound,
            'multiple_basis': _multiple_observation(value['multiple_observation'], company, generated_at),
            'normalization_status': 'CYCLE_AND_ASSUMPTIONS_NOT_CALIBRATED',
            'cash_scope': 'Reported cash and financing inventory; not surplus distributable cash or a human-verified nil balance.'}


def _multiple_observation(value, company, generated_at):
    common = {'fair_multiple_low': None, 'fair_multiple_high': None, 'calibrated': False,
              'missing_basis': ['Approved comparable universe and earnings quality', 'Full-cycle PIT history',
                                'Growth, reinvestment and discount-rate assumptions'],
              'source_authenticity': 'UNVERIFIED', 'rights': 'UNVERIFIED_PRIVATE_LOCAL_ONLY',
              'prospective_sample_eligible': False, 'human_review': 'PENDING'}
    if value is None:
        return {**common, 'status': 'DATA_BLOCKED', 'observed_positive_pe_range': None}
    from research_content import _number
    import research_daily
    materials._exact(value, {'observation', 'observation_hash'})
    source = ev.parse(research_daily.bounded_bytes(value['observation'])); pin = value['observation_hash']
    materials._hash(pin)
    materials._exact(source, {'schema', 'company', 'captured_at', 'cutoff_trade_date', 'source_scope',
                              'source_table', 'source_db_sha256', 'rows', 'observation_hash'})
    # governance-mutation: VALUATION_MULTIPLE_OBSERVATION_PIN
    if source['observation_hash'] != pin or ev.sealed({key: item for key, item in source.items() if key != 'observation_hash'}) != pin:
        _fail('MULTIPLE_PIN')
    if (source['schema'] != 'ar.local-pe-observation.v1' or source['company'] != company
            or source['source_scope'] != research_daily.SCOPE or source['source_table'] != 'raw_daily_basic'):
        _fail('MULTIPLE_SCOPE')
    materials._hash(source['source_db_sha256'])
    captured = materials._time(source['captured_at']); cutoff = materials._date(source['cutoff_trade_date'])
    closed_at = datetime.combine(cutoff, time(15), timezone(timedelta(hours=8)))
    # governance-mutation: VALUATION_MULTIPLE_OBSERVATION_DATE
    if generated_at is None or not closed_at <= captured <= materials._time(generated_at):
        _fail('MULTIPLE_FUTURE')
    rows = source['rows']
    if type(rows) is not list or not 1 <= len(rows) <= 512:
        _fail('MULTIPLE_ROWS')
    dates, positive, missing = [], [], 0
    for row in rows:
        materials._exact(row, {'trade_date', 'pe_ttm', 'pb'})
        day = materials._date(row['trade_date'])
        if day > cutoff:
            _fail('MULTIPLE_FUTURE')
        dates.append(row['trade_date'])
        pe = _number(row['pe_ttm']) if row['pe_ttm'] is not None else None
        if row['pb'] is not None:
            _number(row['pb'])
        if pe is not None and pe > 0:
            positive.append(pe)
        else:
            missing += 1
    if dates != sorted(set(dates)) or dates[-1] != source['cutoff_trade_date']:
        _fail('MULTIPLE_ORDER_OR_CUTOFF')
    return {**common, 'status': 'OBSERVED_MARKET_PE_NOT_FAIR_MULTIPLE', 'observation_hash': pin,
            'source_scope': source['source_scope'], 'source_db_sha256': source['source_db_sha256'],
            'captured_at': source['captured_at'], 'cutoff_trade_date': source['cutoff_trade_date'],
            'row_count': len(rows), 'missing_or_nonpositive_pe_rows': missing,
            'date_range': {'first': dates[0], 'last': dates[-1]},
            'observed_positive_pe_range': {'low': _render(min(positive)), 'high': _render(max(positive))} if positive else None,
            'warning': 'Short retrospective provider PE history mixes earnings vintages; not PIT-certified or a reasonable normalized-PE range.'}
