"""Typed financial reconciliations; reported anchors are not normal earnings."""
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
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


def evaluate(value, facts):
    # Facts are the numeric/quote-verified map from research_content, not claims
    # accepted directly from an untrusted request. Semantic mappings remain E3.
    from research_content import _number
    materials._exact(value, {'schema', 'period', 'nonrecurring', 'anchors', 'cash_inventory'})
    if value['schema'] != 'ar.valuation-basis.v1' or not re.fullmatch(r'\d{4}(FY|H1|Q[1-4])', value['period']):
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
    return {'schema': 'ar.valuation-basis-card.v1',
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
