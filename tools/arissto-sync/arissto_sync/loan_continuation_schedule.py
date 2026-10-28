"""Read-only proof of the final historical-off continuation schedule."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json
from .connections import postgres_connection
from .loan_metric_alignment import amounts

ZERO = Decimal('0.00')
REVIEWED = {'reviewed-manual-adjustment', 'historical-reference-only', 'unordered-source-schedule-dates'}
COLUMNS = ('external_id','loan_id','number','due_date','additional','baseline','forecast',
           'principal','principal_paid','principal_written_off','interest','interest_paid',
           'interest_waived','interest_written_off','audit_id','source_day','targets','after')

def required(lifecycle):
    return (lifecycle.get('interest_recalculation_policy') == 'source-exact-off-v1'
            and str((lifecycle.get('expected') or {}).get('source_state')) == '1'
            and bool(lifecycle.get('final_metric_alignment')))

def load(settings, actions):
    keys = [a['external_id'] for a in actions if a.get('entity_type') == 'loan'
            and a.get('action') != 'quarantine-loan' and required(a.get('lifecycle') or {})]
    if not keys:
        return {}
    if not settings.target.pg_url:
        raise RuntimeError('Target PostgreSQL URL is required for continuation reconciliation')
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute('''
            SELECT l.external_id,l.id,r.installment,r.duedate,r.is_additional,
                   r.migration_metric_baseline,r.migration_interest_forecast,
                   r.principal_amount,r.principal_completed_derived,r.principal_writtenoff_derived,
                   r.interest_amount,r.interest_completed_derived,r.interest_waived_derived,
                   r.interest_writtenoff_derived,a.id,a.source_through_date,a.target_json,a.after_json
            FROM m_loan l JOIN m_loan_repayment_schedule r ON r.loan_id=l.id
            JOIN LATERAL (SELECT id,source_through_date,target_json,after_json
                          FROM credesal_loan_metric_alignment WHERE loan_id=l.id
                          ORDER BY id DESC LIMIT 1) a ON true
            WHERE l.external_id=ANY(%s) ORDER BY l.id,r.installment
        ''', (keys,)).fetchall()
    result = defaultdict(list)
    for row in rows:
        item = dict(zip(COLUMNS, row))
        result[item['external_id']].append(item)
    return result

def verify(loan, action, observation, rows, source_schedule):
    """Require the transformed native rows, not the original settlement amounts."""
    def refuse(reason):
        raise RuntimeError('continuation_schedule_' + reason)
    def money(value):
        number = Decimal(str(value if value is not None else 0))
        if not number.is_finite() or number != number.quantize(Decimal('.01')):
            refuse('invalid_amount')
        return number
    def vector(value):
        return amounts(json.loads(value) if isinstance(value,str) else value)
    lc = action['lifecycle']; frozen = lc['final_metric_alignment']; targets = amounts(frozen['targets'])
    source_day = date.fromisoformat(frozen['cutoffDate']) - timedelta(days=1)
    version = observation.get('alignmentVersion')
    if (loan.get('externalId') != action['external_id'] or loan.get('isInterestRecalculationEnabled') is not False
            or (loan.get('status') or {}).get('id') != 300 or frozen.get('revision') != 1
            or frozen['cutoffDate'] != lc.get('migration_cutover_date')
            or observation.get('loanId') != int(loan['id']) or observation.get('cutoffDate') != frozen['cutoffDate']
            or observation.get('continuationReady') is not True or type(version) is not int or version <= 0
            or amounts(observation['metrics']) != targets or not rows):
        refuse('identity_or_metrics_unproven')
    for r in rows:
        if (r['external_id'] != action['external_id'] or r['loan_id'] != int(loan['id'])
                or r['audit_id'] != version or str(r['source_day']) != str(source_day)
                or vector(r['targets']) != targets or vector(r['after']) != targets):
            refuse('audit_mismatch')
        rday = date.fromisoformat(str(r['due_date']))
        if r['additional'] and rday > source_day:
            refuse('extra_future_installment')
        if money(r['principal']) < money(r['principal_paid']) + money(r['principal_written_off']):
            refuse('negative_principal_outstanding')
        if any(money(r[k]) < 0 for k in ('principal','principal_paid','principal_written_off','interest',
                                         'interest_paid','interest_waived','interest_written_off')):
            refuse('negative_component')
        if r['forecast'] is not None and money(r['forecast']) < 0:
            refuse('negative_forecast')
        if not r['baseline']:
            if (money(r['principal_paid']) != ZERO or money(r['interest_paid']) != ZERO
                    or money(r['interest']) != money(r['interest_waived']) + money(r['interest_written_off'])):
                refuse('nonbaseline_settlement_drift')
            if rday > source_day and r['forecast'] is None:
                refuse('future_forecast_missing')
    base = [r for r in rows if r['baseline']]
    if (len(base) != 1 or not base[0]['additional'] or str(base[0]['due_date']) != str(source_day)
            or base[0]['forecast'] is None or money(base[0]['forecast']) != ZERO):
        refuse('baseline_shape')
    anchor = base[0]
    if (money(anchor['principal_paid']) != money(targets['paidPrincipal'])
            or money(anchor['interest_paid']) != money(targets['paidInterest'])
            or money(anchor['interest']) != money(targets['paidInterest']) + money(targets['accruedInterest'])):
        refuse('baseline_settlement_drift')
    outstanding = lambda r: money(r['principal'])-money(r['principal_paid'])-money(r['principal_written_off'])
    if (sum((outstanding(r) for r in rows),ZERO) != money(targets['outstandingPrincipal'])
            or sum((outstanding(r) for r in rows if str(r['due_date']) <= str(source_day)),ZERO) != money(targets['duePrincipal'])):
        refuse('principal_projection_drift')
    ordered = sorted(rows,key=lambda r:(str(r['due_date']),r['number']))
    if [r['number'] for r in ordered] != list(range(1,len(rows)+1)):
        refuse('installment_order')
    contractual = [r for r in rows if not r['additional']]
    policy = lc.get('schedule_reconciliation_policy')
    if policy not in REVIEWED:
        if Counter(str(r['due_date']) for r in contractual) != Counter(r['due_date'] for r in source_schedule):
            refuse('contractual_calendar_drift')
        source_forecasts = Counter((r['due_date'],money(r['interest'])) for r in source_schedule if r['due_date'] > str(source_day))
        native_forecasts = Counter((str(r['due_date']),money(r['forecast'])) for r in contractual if str(r['due_date']) > str(source_day))
        if source_forecasts != native_forecasts:
            refuse('contractual_forecast_drift')
    return {'baseline_rows':1,'contractual_rows':len(contractual),'reviewed_reference_policy':policy in REVIEWED}
