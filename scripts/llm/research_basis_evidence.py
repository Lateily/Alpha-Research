"""Source-bound financial/daily diagnostics, never a calibrated valuation."""
import argparse
from datetime import timedelta, timezone
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
import re

import foundation_materials as materials
import foundation_research as material
import research_content as content
import research_artifact_io as artifacts
import research_normalization as normalization
import research_valuation as valuation
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials

MARKER = 'basis-manifest.json'
KEYS = {'schema','company','normalization_worksheet','dilution','tax','rd','cash','notes','multiple','daily'}


def _fail(reason):
    raise ev.EvidenceError('RESEARCH_BASIS_' + reason)


def _execution_identity():
    base = normalization._execution_identity()
    root = Path(__file__).resolve().parent
    names = ('research_basis_evidence.py','research_daily_basis.py')
    return {**base,'source_tree_hash':ev.sealed({'base':base['source_tree_hash'],
        'basis':{name:ev.sha(ev.read_local(root,name)) for name in names}})}


def _period(value, bound):
    if type(value) is not str:
        _fail('PERIOD')
    if re.fullmatch(r'\d{8}',value):
        day = materials._date(value)
    elif re.fullmatch(r'\d{4}(?:FY|H1|Q[1-4])',value):
        suffix = {'FY':'1231','H1':'0630','Q1':'0331','Q2':'0630','Q3':'0930','Q4':'1231'}
        day = materials._date(value[:4]+suffix[value[4:]])
    else:
        _fail('PERIOD')
    if day > bound:
        _fail('PERIOD_AFTER_SOURCE_CUTOFF')
    return day


def _rows(value, keys, bound):
    if type(value) is not list or len(value)>8:
        _fail('ROWS')
    periods = []
    for row in value:
        materials._exact(row,{'period',*keys})
        if type(row['period']) is not str or not re.fullmatch(r'\d{4}(?:FY|H1|Q[1-4])',row['period']):
            _fail('EARNINGS_PERIOD_REQUIRED')
        _period(row['period'],bound); periods.append(row['period'])
        refs = [row[key] for key in keys if row[key] is not None]
        if any(type(ref) is not str for ref in refs) or len(refs)!=len(set(refs)):
            _fail('DUPLICATE_REFERENCE')
    if periods != sorted(set(periods)):
        _fail('PERIOD_ORDER')
    return value


def _assumption(row,unit,facts):
    materials._exact(row,{'value','unit','rationale','fact_ids'})
    material._string(row['rationale'],2000)
    content._refs(row['fact_ids'],facts,empty=row['value'] is None)
    if row['unit'] != unit:
        _fail('ASSUMPTION_UNIT')
    return content._number(row['value']) if row['value'] is not None else None


def _quote(citation,read):
    if read is None:
        _fail('QUOTE_SOURCE_REQUIRED')
    materials._exact(citation,{'sha256','page','start','end','expected'})
    materials._hash(citation['sha256']); material._string(citation['expected'],6000)
    if any(type(citation[key]) is not int or citation[key]<1 for key in ('page','start','end')):
        _fail('QUOTE_RANGE')
    lines = read('inputs/pages/'+citation['sha256']+'-p'+str(citation['page'])+'.txt').decode('utf-8').splitlines()
    if citation['end']<citation['start'] or citation['end']>len(lines):
        _fail('QUOTE_RANGE')
    # governance-mutation: BASIS_NOTE_QUOTE
    if '\n'.join(lines[citation['start']-1:citation['end']]) != citation['expected']:
        _fail('QUOTE_MISMATCH')
    return citation


def _cash(value,fact,facts,bound):
    if value is None:
        return {'status':'DATA_BLOCKED','missing_components':sorted(valuation.CASH_COMPONENTS),
                'net_cash_inventory':None,'net_cash_per_share':None,'excess_cash':None,
                'cash_value_credit_allowed':False}
    materials._exact(value,{'period','components','declared_equivalents','excluded_from_equivalents',
                           'excluded_components','operating_reserve'})
    period=value['period']; materials._date(period); _period(period,bound)
    materials._exact(value['components'],valuation.CASH_COMPONENTS)
    refs=[ref for ref in value['components'].values() if ref is not None]
    if len(refs)!=len(set(refs)):
        _fail('CASH_DUPLICATE_REFERENCE')
    numbers={key:fact(ref,'COUNT' if key=='period_end_shares' else 'CNY',period)
             for key,ref in value['components'].items()}
    if any(number is not None and number<0 for number in numbers.values()):
        _fail('CASH_NEGATIVE')
    shares=numbers['period_end_shares']
    if shares is not None and (shares<=0 or shares!=int(shares)):
        _fail('CASH_SHARES')
    missing=sorted(key for key,number in numbers.items() if number is None)
    money=numbers['cash']; deductions=valuation.CASH_COMPONENTS-{'cash','period_end_shares'}
    known=sum(numbers[key] for key in deductions if numbers[key] is not None)
    residual=money-known if money is not None else None
    # governance-mutation: BASIS_CASH_NO_IMPUTATION
    net=residual if not missing else None
    per_share=(net/shares).quantize(Decimal('0.00000001')) if net is not None else None
    cash_eq=fact(value['declared_equivalents'],'CNY',period)
    excluded=fact(value['excluded_from_equivalents'],'CNY',period)
    detail=value['excluded_components']
    if type(detail) is not list or len(detail)>32 or any(type(ref) is not str for ref in detail) or len(detail)!=len(set(detail)):
        _fail('CASH_EXCLUDED_COMPONENTS')
    parts=[fact(ref,'CNY',period) for ref in detail]
    if any(x is not None and x<0 for x in [cash_eq,excluded,*parts]):
        _fail('CASH_EQUIVALENT_RANGE')
    part_total=sum(parts) if parts else None
    inferred=money-excluded if money is not None and excluded is not None else None
    # governance-mutation: BASIS_CASH_EQUIVALENT_RECONCILIATION
    matched=(inferred is not None and cash_eq is not None and part_total is not None
             and inferred==cash_eq and part_total==excluded)
    reserve=_assumption(value['operating_reserve'],'CNY',facts)
    if reserve is not None and reserve<0:
        _fail('OPERATING_RESERVE_RANGE')
    render=lambda number: content._decimal(number) if number is not None else None
    return {**value,'status':'DATA_BLOCKED' if missing or not matched else 'INVENTORY_ARITHMETIC_SEMANTICS_UNVERIFIED',
        'observed_components':{key:render(number) for key,number in numbers.items()},
        'missing_components':missing,'known_component_residual':render(residual),
        'residual_scope':'KNOWN_COMPONENTS_ONLY_NOT_NET_OR_SURPLUS_CASH',
        'net_cash_inventory':render(net),'net_cash_per_share':render(per_share),
        'cash_equivalent_bridge':{'status':'ARITHMETIC_RECONCILED_SEMANTICS_UNVERIFIED' if matched else 'DATA_BLOCKED',
            'money_funds_less_excluded':render(inferred),'declared_equivalents':render(cash_eq),
            'excluded_components_total':render(part_total),'declared_excluded':render(excluded),
            'warning':'Non-equivalent deposits/accruals are not automatically legal restrictions or surplus cash.'},
        'hypothetical_residual_after_reserve':render(net-reserve) if net is not None and reserve is not None else None,
        'excess_cash':None,'cash_value_credit_allowed':False,
        'interest_allocation':'OPERATING_VS_EXCESS_CASH_INTEREST_UNRESOLVED','human_review':'PENDING'}


def _multiple(value,facts):
    materials._exact(value,{'discount_pct','growth_pct','payout_pct'})
    numbers={key:_assumption(row,'PCT',facts) for key,row in value.items()}
    d,g,p=(numbers[key] for key in ('discount_pct','growth_pct','payout_pct'))
    if ((d is not None and not 0<d<=100) or (g is not None and not -100<g<100)
            or (p is not None and not 0<=p<=100)):
        _fail('MULTIPLE_RANGE')
    # governance-mutation: BASIS_MULTIPLE_SPREAD
    if d is not None and g is not None and g>=d:
        _fail('MULTIPLE_NONPOSITIVE_SPREAD')
    result=(p/100)*(1+g/100)/((d-g)/100) if all(x is not None for x in (d,g,p)) else None
    return {'status':'HYPOTHETICAL_STABLE_GROWTH_E4' if result is not None else 'DATA_BLOCKED',
        'formula':'(payout_pct/100)*(1+growth_pct/100)/((discount_pct-growth_pct)/100)',
        'hypothetical_trailing_pe':content._decimal(result.quantize(Decimal('0.00000001'))) if result is not None else None,
        'assumptions':value,'fair_multiple_low':None,'fair_multiple_high':None,
        'calibrated':False,'evidence_tier':'E4','human_review':'PENDING',
        'warning':'Stable payout/growth/discount sensitivity is not a full-cycle comparable or reasonable multiple calibration.'}


def derive(cards,worksheet,*,read=None):
    """Only public create/verify supply quote-verified cards and pinned page reads."""
    materials._exact(worksheet,KEYS)
    if worksheet['schema']!='ar.research-basis-worksheet.v1' or worksheet['company']!=cards['company']:
        _fail('IDENTITY')
    facts={row['id']:row for row in cards['facts']['observations']}
    if len(facts)!=len(cards['facts']['observations']):
        _fail('DUPLICATE_FACT')
    cn=timezone(timedelta(hours=8))
    bound=min(materials._time(cards[name]).astimezone(cn).date() for name in ('material_cutoff_at','generated_at'))
    def fact(ref,unit,period):
        if ref is None:
            return None
        # governance-mutation: BASIS_REFERENCE_TYPES
        if type(ref) is not str or ref not in facts or facts[ref]['unit']!=unit or facts[ref]['period']!=period:
            _fail('REFERENCE_UNIT_PERIOD')
        return content._number(facts[ref]['value'])
    render=lambda number:content._decimal(number) if number is not None else None
    dilutions=[]; tax=[]; rd=[]
    with localcontext(Context(prec=80,rounding=ROUND_HALF_UP)):
        for row in _rows(worksheet['dilution'],{'profit','reported_eps','basic_shares','diluted_shares'},bound):
            period=row['period']; profit=fact(row['profit'],'CNY',period); eps=fact(row['reported_eps'],'CNY_PER_SHARE',period)
            basic=fact(row['basic_shares'],'COUNT',period); diluted=fact(row['diluted_shares'],'COUNT',period)
            if any(x is not None and (x<=0 or x!=int(x)) for x in (basic,diluted)):
                _fail('DILUTION_DENOMINATOR')
            calculated=(profit/diluted).quantize(Decimal('0.01')) if profit is not None and diluted is not None else None
            # governance-mutation: BASIS_DILUTION_RECONCILIATION
            matched=all(x is not None for x in (profit,eps,basic,diluted)) and calculated==eps
            dilutions.append({**row,'status':'REPORTED_ARITHMETIC_RECONCILED_NOT_NORMALIZED' if matched else 'DATA_BLOCKED',
                'reported_denominator':render(diluted),'basic_denominator':render(basic),
                'recomputed_reported_eps':render(calculated),'comparison_convention':'ROUND_HALF_UP_2DP_NOT_DENOMINATOR_INFERENCE',
                'normalized_eps':None})
        for row in _rows(worksheet['tax'],{'pretax','current','deferred','total'},bound):
            n={key:fact(row[key],'CNY',row['period']) for key in ('pretax','current','deferred','total')}
            total=n['current']+n['deferred'] if n['current'] is not None and n['deferred'] is not None else None
            matched=total is not None and n['total'] is not None and total==n['total']
            rate=(n['total']/n['pretax']*100).quantize(Decimal('0.00000001')) if n['pretax'] not in (None,0) and n['total'] is not None else None
            tax.append({**row,'status':'REPORTED_ARITHMETIC_RECONCILED_NOT_NORMALIZED' if matched else 'DATA_BLOCKED',
                'current_plus_deferred':render(total),'reported_effective_tax_pct':render(rate),'normal_tax_pct':None})
        for row in _rows(worksheet['rd'],{'expense','capitalized','total'},bound):
            n={key:fact(row[key],'CNY',row['period']) for key in ('expense','capitalized','total')}
            if any(number is not None and number<0 for number in n.values()):
                _fail('RD_RANGE')
            total=n['expense']+n['capitalized'] if n['expense'] is not None and n['capitalized'] is not None else None
            matched=total is not None and n['total'] is not None and total==n['total']
            ratio=(n['capitalized']/total*100).quantize(Decimal('0.00000001')) if total not in (None,0) else None
            rd.append({**row,'status':'REPORTED_ARITHMETIC_RECONCILED_NOT_NORMALIZED' if matched else 'DATA_BLOCKED',
                'expense_plus_capitalized':render(total),'capitalized_pct':render(ratio),'normalization_adjustment':None})
        cash=_cash(worksheet['cash'],fact,facts,bound)
        multiple=_multiple(worksheet['multiple'],facts)
    notes=worksheet['notes']
    if type(notes) is not list or len(notes)>16:
        _fail('NOTES')
    bound_notes=[]
    for row in notes:
        materials._exact(row,{'topic','period','citation'}); _period(row['period'],bound)
        if row['topic'] not in {'cycle','tax_policy','cash_scope','financing','capital_commitment','share_count','comparability'}:
            _fail('NOTE_TOPIC')
        bound_notes.append({**row,'citation':_quote(row['citation'],read),
            'status':'QUOTE_VERIFIED_INTERPRETATION_PENDING','numeric_zero_inferred':False,'human_review':'PENDING'})
    normal=normalization.derive(cards,worksheet['normalization_worksheet'])
    if worksheet['daily'] is None:
        daily={'status':'DATA_BLOCKED','eligible':False,'reason_codes':['DAILY_EVIDENCE_NOT_SUPPLIED']}
    else:
        import research_daily_basis
        daily=research_daily_basis.derive(worksheet['daily'],facts,read,company=cards['company'],generated_at=cards['generated_at'])
    return {'schema':'ar.research-basis-card.v1','company':cards['company'],
        'generated_at':cards['generated_at'],'material_cutoff_at':cards['material_cutoff_at'],
        'status':'BASIS_EVIDENCE_PARTIAL','dilution':dilutions,'tax':tax,'rd':rd,'cash':cash,
        'notes':bound_notes,'multiple':multiple,'normalization':normal,'daily':daily,
        'normalized_eps':None,'value_band':None,'calibrated':False,'source_authenticity':'UNVERIFIED',
        'rights':'UNVERIFIED_PRIVATE_LOCAL_ONLY',**content.LABELS}


def _files(raw,pin,content_root,content_hash,pack_root,pack_hash):
    materials._hash(pin)
    if type(raw) is not bytes or len(raw)>ev.MAX_FILE:
        _fail('INPUT_SIZE_OR_TYPE')
    # governance-mutation: BASIS_WORKSHEET_PIN
    if ev.sha(raw)!=pin:
        _fail('WORKSHEET_PIN')
    worksheet=ev.parse(raw); reject_credentials(worksheet)
    cards=normalization._snapshot(content_root,content_hash,pack_root,pack_hash)
    _,read=content._pack(materials._root(pack_root),pack_hash)
    result=derive(cards,worksheet,read=read)
    report=('# Research Basis Evidence\n\nWORKFLOW_DEBUG; human PENDING; not a calibrated valuation.\n\n'
            +content.text(result)+'\n\nNot a trading instruction; research signal, human executes.\n').encode()
    return {'worksheet.json':raw,'basis-card.json':ev.canonical(result).encode(),'report.md':report}


def create(raw,pin,content_root,content_hash,pack_root,pack_hash,output_root):
    output=materials._root(output_root)
    for path in (content_root,pack_root):
        source=materials._root(path)
        if output==source or output in source.parents or source in output.parents:
            _fail('ROOT_OVERLAP')
    identity=_execution_identity()
    files=_files(raw,pin,content_root,content_hash,pack_root,pack_hash)
    manifest={'schema':'ar.research-basis-manifest.v1','content_hash':content_hash,'pack_hash':pack_hash,
        'worksheet_hash':pin,'execution_identity':identity,'files':{name:ev.sha(data) for name,data in files.items()},**content.LABELS}
    manifest['basis_hash']=ev.sealed(manifest); encoded=ev.canonical(manifest).encode()
    if _execution_identity()!=identity:
        _fail('CODE_CHANGED')
    if any(len(data)>ev.MAX_FILE for data in (*files.values(),encoded)):
        _fail('OUTPUT_SIZE')
    return artifacts.publish(output,files,MARKER,encoded,
        lambda:verify(output,manifest['basis_hash'],content_root,content_hash,pack_root,pack_hash))


def verify(output_root,pin,content_root,content_hash,pack_root,pack_hash):
    materials._hash(pin)
    with artifacts.read(output_root,{'worksheet.json','basis-card.json','report.md',MARKER}) as saved:
        manifest=ev.parse(saved[MARKER])
        materials._exact(manifest,{'schema','content_hash','pack_hash','worksheet_hash','execution_identity','files','basis_hash',*content.LABELS})
        if (manifest['schema']!='ar.research-basis-manifest.v1' or manifest['basis_hash']!=pin
                or ev.sealed({key:value for key,value in manifest.items() if key!='basis_hash'})!=pin
                or manifest['content_hash']!=content_hash or manifest['pack_hash']!=pack_hash
                or any(type(manifest[key]) is not type(value) or manifest[key]!=value for key,value in content.LABELS.items())):
            _fail('MANIFEST_PIN')
        materials._exact(manifest['files'],{'worksheet.json','basis-card.json','report.md'})
        materials._exact(manifest['execution_identity'],{'code_sha','source_tree_hash'})
        materials._hash(manifest['execution_identity']['code_sha'],40); materials._hash(manifest['execution_identity']['source_tree_hash'])
        expected=_files(saved['worksheet.json'],manifest['worksheet_hash'],content_root,content_hash,pack_root,pack_hash)
        # governance-mutation: BASIS_DERIVATION
        if any(saved[name]!=data or ev.sha(data)!=manifest['files'][name] for name,data in expected.items()):
            _fail('DERIVATION')
        return {'schema':'ar.research-basis-receipt.v1','basis_hash':pin,'content_hash':content_hash,'pack_hash':pack_hash,
            'report_sha256':manifest['files']['report.md'],'status':'BASIS_EVIDENCE_PARTIAL',**content.LABELS}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('command',choices=('create','verify'))
    for name in ('content-root','content-hash','pack-root','pack-hash','output'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--worksheet'); parser.add_argument('--worksheet-hash'); parser.add_argument('--basis-hash')
    args=parser.parse_args(); values=(Path(args.content_root),args.content_hash,Path(args.pack_root),args.pack_hash)
    if args.command=='create':
        if args.worksheet is None or args.worksheet_hash is None: parser.error('worksheet and external hash required')
        path=Path(args.worksheet); result=create(ev.read_local(path.parent,path.name),args.worksheet_hash,*values,Path(args.output))
    else:
        if args.basis_hash is None: parser.error('external basis hash required')
        result=verify(Path(args.output),args.basis_hash,*values)
    print(ev.canonical(result))


if __name__=='__main__': main()
