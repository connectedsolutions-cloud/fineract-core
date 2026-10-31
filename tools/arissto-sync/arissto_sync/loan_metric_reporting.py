"""Active eight-metric reporting; schedule references never become financial failures."""
from collections import Counter
from datetime import date,timedelta
from decimal import Decimal
from .loan_metric_alignment import METRICS,eligible,observed_amounts
from .connections import postgres_connection


def load_insurance_breakdown(settings,actions,cutoff):
    selected=[a for a in actions if a.get('entity_type')=='loan' and a.get('action')!='quarantine-loan'
              and eligible(a.get('lifecycle') or {}) and a['lifecycle'].get('final_metric_alignment')]
    if not selected:return {}
    if not settings.target.pg_url:raise RuntimeError('Native insurance reporting requires PostgreSQL inspection')
    by_external={a['external_id']:a for a in selected}
    with postgres_connection(settings.target.pg_url) as conn:
        rows=conn.execute("""SELECT l.external_id,c.id,c.charge_id,c.amount_outstanding_derived,
                 c.due_for_collection_as_of_date,i.id,r.duedate,i.amount_outstanding_derived
            FROM m_loan l JOIN m_loan_charge c ON c.loan_id=l.id AND c.is_active AND NOT c.is_penalty
            LEFT JOIN m_loan_installment_charge i ON i.loan_charge_id=c.id
            LEFT JOIN m_loan_repayment_schedule r ON r.id=i.loan_schedule_id
            WHERE l.external_id=ANY(%s)""",(list(by_external),)).fetchall()
    source_day=date.fromisoformat(cutoff)-timedelta(days=1)
    totals={k:{'owed':Decimal(0),'future':Decimal(0),'undated':Decimal(0),'scheduled':Decimal(0)} for k in by_external}
    seen=set()
    for external,charge,definition,parent_amount,parent_day,installment,installment_day,installment_amount in rows:
        frozen=by_external[external]['lifecycle']['final_metric_alignment']
        if definition not in {frozen['insuranceChargeId'],frozen['recurringInsuranceChargeId']}:continue
        t=totals[external]
        if charge not in seen:
            t['scheduled']+=Decimal(str(parent_amount or 0)).quantize(Decimal('.01'));seen.add(charge)
        day=installment_day if installment is not None else parent_day
        amount=Decimal(str(installment_amount if installment is not None else parent_amount or 0)).quantize(Decimal('.01'))
        t['owed' if day and day<=source_day else 'future' if day else 'undated']+=amount
    return {key:{name:format(value,'.2f') for name,value in values.items()} for key,values in totals.items()}


def build_active_metric_report(actions,result):
    selected={a['source_key']:a for a in actions if a.get('entity_type')=='loan'
              and a.get('action')!='quarantine-loan' and eligible(a.get('lifecycle') or {})}
    records={r['source_key']:r for r in result.get('metric_observations',[]) if r.get('source_key') in selected}
    mismatches=[r for r in result.get('mismatches',[]) if r.get('source_key') in selected
                and (str(r.get('kind','')).startswith('final_metric:')
                     or r.get('kind') in {'final_metric_observation_invalid','final_metric_continuation_missing'})]
    # Older accepted reports proved the full vector in the strict continuation
    # verifier; that verifier refuses any missing/nonmatching metric or identity.
    legacy_verified=(not records and bool(result.get('ok')) and not mismatches
        and result.get('counts',{}).get('continuation_schedules_reconciled')==len(selected)
        and all(a['lifecycle'].get('final_metric_alignment') for a in selected.values()))
    per_metric={k:{'expected':len(selected),'checked':0,'matched':0,'mismatched':0} for k in METRICS}
    insurance=[]
    observation_errors=[]
    for key,a in selected.items():
        record=records.get(key)
        if record:
            try:
                actual=observed_amounts(record['actual']);expected=observed_amounts(a['lifecycle']['final_metric_alignment']['targets'])
            except (RuntimeError,KeyError,ValueError,ArithmeticError):
                observation_errors.append(key);continue
            for metric in METRICS:
                per_metric[metric]['checked']+=1
                per_metric[metric]['matched' if actual[metric]==expected[metric] else 'mismatched']+=1
            split=record.get('insurance') or {}
            consistent=(split.get('owed')==actual['insuranceOutstanding'] and split.get('undated')=='0.00'
                and all(split.get(k) is not None for k in ['owed','future','scheduled'])
                and Decimal(split['scheduled'])==Decimal(split['owed'])+Decimal(split['future']))
            insurance.append({'source_key':key,'insuranceOwed':actual['insuranceOutstanding'],
                'futureInsurance':split.get('future') if consistent else None,
                'scheduledInsurance':split.get('scheduled') if consistent else None,
                'verified':consistent})
        elif legacy_verified:
            for metric in METRICS:per_metric[metric]['checked']+=1;per_metric[metric]['matched']+=1
    refs=result.get('variances',[])
    active_refs=[r for r in refs if r.get('source_key') in selected]
    groups=Counter((str(r.get('classification') or 'unclassified'),str(r.get('kind') or 'unclassified')) for r in active_refs)
    matched=sum(v['matched'] for v in per_metric.values());checked=sum(v['checked'] for v in per_metric.values())
    mismatch_count=sum(v['mismatched'] for v in per_metric.values())
    complete=(checked==len(selected)*len(METRICS) and not observation_errors)
    return {'scope':'active-eight-metrics','active_loans':len(selected),'metric_count':len(METRICS),
        'expected_checks':len(selected)*len(METRICS),'checked':checked,'matched':matched,
        'mismatched':mismatch_count,'complete':complete,'ok':complete and mismatch_count==0 and not mismatches,
        'verification_basis':'strict-recorded-continuation' if legacy_verified else 'native-metric-observations',
        'metrics':per_metric,'metric_failures':mismatches,'observation_errors':observation_errors,
        'insurance':insurance,'insurance_breakdowns_verified':sum(x['verified'] for x in insurance),
        'reference_details':{'active_count':len(active_refs),'inactive_count':len(refs)-len(active_refs),
            'expected_schedule_count':sum(r.get('classification')=='verified_final_continuation_schedule_variance' for r in active_refs),
            'groups':[{'classification':c,'kind':k,'count':n} for (c,k),n in sorted(groups.items())]},
        'integrity_mismatch_count':len(result.get('mismatches',[]))-len(mismatches)}
