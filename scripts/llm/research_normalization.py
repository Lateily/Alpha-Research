"""Reported earnings bridges and explicit E4 hypotheses, never financial approval."""
import argparse
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

import foundation_materials as materials
import foundation_research as material
import research_content as content
import research_artifact_io as artifacts
import workbench_backup as backup
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials

UNITS = {'revenue': 'CNY', 'gross_margin_pct': 'PCT', 'operating_expenses': 'CNY',
         'net_operating_adjustments': 'CNY', 'tax_pct': 'PCT', 'diluted_shares': 'COUNT'}
MARKER = 'normalization-manifest.json'


def _fail(reason):
    raise ev.EvidenceError('NORMALIZATION_' + reason)


def _execution_identity():
    base = content._execution_identity()
    root = Path(__file__).resolve().parent
    hashes = {name: ev.sha(ev.read_local(root, name)) for name in ('research_normalization.py', 'research_artifact_io.py')}
    return {**base, 'source_tree_hash': ev.sealed({'base': base['source_tree_hash'], 'normalization': hashes})}


def derive(cards, worksheet):
    """Only create/verify supply quote-verified cards; this helper grants no trust."""
    materials._exact(worksheet, {'schema', 'company', 'assumptions', 'interest_policy', 'interest_reconciliation', 'dilution_anchors'})
    if worksheet['schema'] != 'ar.normalization-worksheet.v1' or worksheet['company'] != cards['company']:
        _fail('IDENTITY')
    facts = {row['id']: row for row in cards['facts']['observations']}
    if len(facts) != len(cards['facts']['observations']):
        _fail('DUPLICATE_FACT')
    materials._exact(worksheet['assumptions'], set(UNITS))
    supplied = {}
    for key, row in worksheet['assumptions'].items():
        materials._exact(row, {'value', 'unit', 'rationale', 'fact_ids'})
        material._string(row['rationale'], 2000)
        content._refs(row['fact_ids'], facts, empty=row['value'] is None)
        if row['unit'] != UNITS[key]:
            _fail('ASSUMPTION_UNIT')
        number = content._number(row['value']) if row['value'] is not None else None
        # governance-mutation: NORMALIZATION_ASSUMPTION_RANGE
        if number is not None and ((key == 'tax_pct' and not 0 <= number <= 100)
                or (key == 'gross_margin_pct' and number > 100)
                or (key in ('revenue', 'diluted_shares') and number <= 0)
                or (key == 'operating_expenses' and number < 0)):
            _fail('ASSUMPTION_RANGE')
        supplied[key] = number
    if worksheet['interest_policy'] not in ('UNRESOLVED', 'EXCLUDED_FROM_OPERATING_EARNINGS'):
        _fail('INTEREST_POLICY')
    interest = worksheet['interest_reconciliation']
    if interest is not None:
        materials._exact(interest, {'fact_ids', 'rationale'})
        content._refs(interest['fact_ids'], facts)
        material._string(interest['rationale'], 2000)
    if worksheet['interest_policy'] == 'EXCLUDED_FROM_OPERATING_EARNINGS' and interest is None:
        _fail('INTEREST_RECONCILIATION_REQUIRED')
    dilution = []
    periods = set()
    if not isinstance(worksheet['dilution_anchors'], list) or len(worksheet['dilution_anchors']) > 12:
        _fail('DILUTION_ANCHORS')
    for anchor in worksheet['dilution_anchors']:
        materials._exact(anchor, {'period', 'profit_fact_id', 'diluted_eps_fact_id', 'denominator_fact_id'})
        material._string(anchor['period'], 100)
        if anchor['period'] in periods:
            _fail('DILUTION_DUPLICATE_PERIOD')
        periods.add(anchor['period'])
        values = {}
        for key, unit in (('profit_fact_id', 'CNY'), ('diluted_eps_fact_id', 'CNY_PER_SHARE'), ('denominator_fact_id', 'COUNT')):
            ref = anchor[key]
            if ref is None and key == 'denominator_fact_id':
                values[key] = None
                continue
            content._refs([ref], facts)
            if facts[ref]['unit'] != unit or facts[ref]['period'] != anchor['period']:
                _fail('DILUTION_REFERENCE')
            value = content._number(facts[ref]['value'])
            if key == 'denominator_fact_id' and value <= 0:
                _fail('DILUTION_RANGE')
            values[key] = value
        dilution.append({'period': anchor['period'], 'references': anchor,
            'reported_profit': content._decimal(values['profit_fact_id']),
            'reported_diluted_eps': content._decimal(values['diluted_eps_fact_id']),
            'weighted_diluted_shares': content._decimal(values['denominator_fact_id']) if values['denominator_fact_id'] is not None else None,
            'status': 'DENOMINATOR_NOT_DISCLOSED' if values['denominator_fact_id'] is None else 'REPORTED_NOT_NORMALIZED',
            'warning': 'Never infer a precise weighted denominator from rounded reported EPS.'})

    def number(row, key):
        ref = row['references'].get(key)
        if ref is None:
            return None
        # governance-mutation: NORMALIZATION_REPORTED_TYPES
        if ref not in facts or facts[ref]['period'] != row['period'] or facts[ref]['unit'] != 'CNY':
            _fail('REPORTED_REFERENCE')
        return content._number(facts[ref]['value'])

    render = lambda x: content._decimal(x) if x is not None else None
    bridges = []
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        for row in cards['valuation'].get('earnings_history', []):
            revenue, cost = number(row, 'revenue'), number(row, 'operating_cost')
            expenses = [number(row, key) for key in ('selling_expense', 'admin_expense', 'rd_expense')]
            pretax, cash_interest = number(row, 'pre_tax_profit'), number(row, 'interest_income')
            tax = number(row, 'tax_expense')
            gross = revenue - cost if revenue is not None and cost is not None else None
            opex = sum(expenses) if all(x is not None for x in expenses) else None
            subtotal = gross - opex if gross is not None and opex is not None else None
            bridges.append({'period': row['period'], 'references': row['references'],
                'gross_profit': render(gross), 'sales_admin_rd': render(opex),
                'gross_less_sales_admin_rd': render(subtotal),
                'residual_to_pretax': render(pretax - subtotal) if pretax is not None and subtotal is not None else None,
                'pretax_less_reported_interest_income': render(pretax - cash_interest) if pretax is not None and cash_interest is not None else None,
                'reported_effective_tax_pct': render((tax / pretax * 100).quantize(Decimal('0.00000001'))) if pretax not in (None, 0) and tax is not None else None,
                'status': 'REPORTED_ARITHMETIC_NOT_EBIT_OR_NORMAL_EARNINGS',
                'warning': 'Residual includes omitted operating/financial lines; all cash interest is not necessarily excess-cash income; reported effective tax is not a normal tax assumption.'})
        missing = sorted(key for key, value in supplied.items() if value is None)
        eps = operating = after_tax = None
        # governance-mutation: NORMALIZATION_NO_IMPUTATION
        if not missing and worksheet['interest_policy'] == 'EXCLUDED_FROM_OPERATING_EARNINGS':
            operating = (supplied['revenue'] * supplied['gross_margin_pct'] / 100
                         - supplied['operating_expenses'] + supplied['net_operating_adjustments'])
            after_tax = operating * (1 - supplied['tax_pct'] / 100)
            eps = (after_tax / supplied['diluted_shares']).quantize(Decimal('0.00000001'))
    return {'schema': 'ar.normalization-card.v1', 'company': cards['company'],
        'financial_material_cutoff': cards['material_cutoff_at'], 'source_draft_generated_at': cards['generated_at'],
        'status': 'NORMALIZATION_BASIS_PARTIAL', 'reported_bridges': bridges, 'reported_dilution': dilution,
        'assumptions': worksheet['assumptions'], 'scenario': {
            'status': 'HYPOTHETICAL_UNCALIBRATED_E4' if eps is not None else 'DATA_BLOCKED',
            'formula': '(revenue*gross_margin_pct/100-operating_expenses+net_operating_adjustments)*(1-tax_pct/100)/diluted_shares',
            'operating_profit': render(operating), 'after_tax_profit': render(after_tax), 'eps': render(eps),
            'missing_assumptions': missing, 'interest_policy': worksheet['interest_policy'],
            'interest_reconciliation': interest, 'evidence_tier': 'E4', 'human_review': 'PENDING'},
        'cash_inventory': cards['valuation'].get('cash_inventory'),
        'multiple_basis': cards['valuation'].get('multiple_basis'),
        'normalized_eps': None, 'value_band': None, 'calibrated': False,
        'source_authenticity': 'UNVERIFIED', 'financial_semantics': 'UNVERIFIED',
        'rights': 'UNVERIFIED_PRIVATE_LOCAL_ONLY', 'target_price': False, **content.LABELS}


def _snapshot(content_root, content_hash, pack_root, pack_hash):
    content.verify(content_root, content_hash, pack_root, pack_hash)
    manifest = ev.parse(ev.read_local(content_root, 'content-manifest.json'))
    # governance-mutation: NORMALIZATION_SOURCE_SNAPSHOT
    if manifest['content_hash'] != content_hash or ev.sealed({k: v for k, v in manifest.items() if k != 'content_hash'}) != content_hash:
        _fail('SOURCE_PIN')
    raw = ev.read_local(content_root, 'cards.json')
    if ev.sha(raw) != manifest['files']['cards.json']:
        _fail('SOURCE_CHANGED')
    return ev.parse(raw)


def _files(raw, worksheet_hash, cards):
    materials._hash(worksheet_hash)
    if ev.sha(raw) != worksheet_hash:
        _fail('WORKSHEET_PIN')
    worksheet = ev.parse(raw); reject_credentials(worksheet)
    result = derive(cards, worksheet)
    report = ('# Normalization Evidence Draft\n\nWORKFLOW_DEBUG; E4 assumptions; human PENDING.\n\n'
              + content.text(result) + '\n\nNot a trading instruction; research signal, human executes.\n').encode()
    return {'worksheet.json': raw, 'normalization-card.json': ev.canonical(result).encode(), 'report.md': report}


def create(raw, worksheet_hash, content_root, content_hash, pack_root, pack_hash, output_root):
    output = materials._root(output_root)
    for path in (content_root, pack_root):
        source = materials._root(path)
        if output == source or output in source.parents or source in output.parents:
            _fail('ROOT_OVERLAP')
    identity = _execution_identity()
    cards = _snapshot(content_root, content_hash, pack_root, pack_hash)
    files = _files(raw, worksheet_hash, cards)
    manifest = {'schema': 'ar.normalization-manifest.v1', 'content_hash': content_hash,
                'pack_hash': pack_hash, 'worksheet_hash': worksheet_hash,
                'execution_identity': identity, 'files': {k: ev.sha(v) for k, v in files.items()}, **content.LABELS}
    manifest['normalization_hash'] = ev.sealed(manifest)
    encoded = ev.canonical(manifest).encode()
    if _execution_identity() != identity:
        _fail('CODE_CHANGED')
    if any(len(value) > ev.MAX_FILE for value in (*files.values(), encoded)):
        _fail('OUTPUT_SIZE')
    return artifacts.publish(output, files, MARKER, encoded,
        lambda: verify(output, manifest['normalization_hash'], content_root, content_hash, pack_root, pack_hash))


def verify(output_root, pin, content_root, content_hash, pack_root, pack_hash):
    with artifacts.read(output_root, {'worksheet.json', 'normalization-card.json', 'report.md', MARKER}) as raw:
        return _verify(raw, pin, content_root, content_hash, pack_root, pack_hash)


def _verify(saved, pin, content_root, content_hash, pack_root, pack_hash):
    materials._hash(pin)
    manifest = ev.parse(saved[MARKER])
    materials._exact(manifest, {'schema', 'content_hash', 'pack_hash', 'worksheet_hash', 'execution_identity',
                              'files', 'normalization_hash', *content.LABELS})
    if (manifest['schema'] != 'ar.normalization-manifest.v1' or manifest['normalization_hash'] != pin
            or ev.sealed({k: v for k, v in manifest.items() if k != 'normalization_hash'}) != pin
            or manifest['content_hash'] != content_hash or manifest['pack_hash'] != pack_hash
            or any(type(manifest[k]) is not type(v) or manifest[k] != v for k, v in content.LABELS.items())):
        _fail('MANIFEST_PIN')
    materials._exact(manifest['files'], {'worksheet.json', 'normalization-card.json', 'report.md'})
    materials._exact(manifest['execution_identity'], {'code_sha', 'source_tree_hash'})
    materials._hash(manifest['execution_identity']['code_sha'], 40)
    materials._hash(manifest['execution_identity']['source_tree_hash'])
    raw = saved['worksheet.json']
    expected = _files(raw, manifest['worksheet_hash'], _snapshot(content_root, content_hash, pack_root, pack_hash))
    # governance-mutation: NORMALIZATION_DERIVATION
    if any(ev.sha(value) != manifest['files'][name] or saved[name] != value for name, value in expected.items()):
        _fail('DERIVATION')
    return {'normalization_hash': pin, 'content_hash': content_hash, 'pack_hash': pack_hash,
            'report_sha256': manifest['files']['report.md'], 'status': 'NORMALIZATION_BASIS_PARTIAL', **content.LABELS}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=('create', 'verify'))
    for name in ('content-root', 'content-hash', 'pack-root', 'pack-hash', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--worksheet'); parser.add_argument('--worksheet-hash'); parser.add_argument('--normalization-hash')
    args = parser.parse_args(); values = (Path(args.content_root), args.content_hash, Path(args.pack_root), args.pack_hash)
    if args.command == 'create':
        if args.worksheet is None or args.worksheet_hash is None: parser.error('worksheet and external hash required')
        path = Path(args.worksheet); raw = ev.read_local(path.parent, path.name)
        output = create(raw, args.worksheet_hash, *values, Path(args.output))
    else:
        if args.normalization_hash is None: parser.error('normalization hash required')
        output = verify(Path(args.output), args.normalization_hash, *values)
    print(ev.canonical(output))


if __name__ == '__main__':
    main()
