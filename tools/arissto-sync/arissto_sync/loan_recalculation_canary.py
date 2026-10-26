"""Isolated local-sandbox paired ordinary-interest experiment.

Frozen plan -> apply -> report. This is not a migration service and cannot
change existing canonical products or loans, tenant dates, or source records.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .config import ROOT, load_settings
from .arissto import source_connection, select_rows
from .connections import FineractApi, postgres_connection
from .loans import (_find_loan, _ensure_source_exact_pending_schedule,
    _loan_schedule_differences)
from .loan_daily_interest_canary import native_interest_as_of

NAMESPACE = 'recalc-oct19-a'
KEYS = ('2612','2647','2581','2597','2593')
DIRECTORY = ROOT / '.arissto-sync' / 'loan-recalculation-canaries'
S, T = '2026-10-19', '2026-10-20'

SOURCE_QUERIES = {
    'terms': """SELECT c.ID_CREDITO,c.MONTO_DESEMBOLSADO,c.INTERES_MONTO_APROBADO,
        c.FECHA_OTORGAMIENTO,c.FECHA_PRIMER_PAGO,c.PLAZO_APROBADO,c.ID_FRECUENCIA,
        c.ID_ESTADO_CARTERA,RTRIM(a.NUMERO_AFILIACION) AS client_external_id
        FROM dbo.CRD_CARTERA c JOIN dbo.AFI_SOCIO a ON a.ID_EMPRESA=c.ID_EMPRESA
          AND a.ID_SUCURSAL=c.ID_SUCURSAL_SOCIO AND a.ID_SOCIO=c.ID_SOCIO
        WHERE c.ID_CREDITO=?""",
    'schedule': """SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES,
        SALDO_ANTERIOR,SALDO_ACTUAL FROM dbo.CRD_PLAN_PAGO
        WHERE ID_CREDITO=? ORDER BY NO_CUOTA""",
    'movements': """SELECT RTRIM(ID_MOVIMIENTO_CARTERA) AS movement_id,
        CODIGO_SISTEMA,RTRIM(ID_TRANSACCION) AS transaction_code,FECHA_OPERACION,
        REVERSION,MONTO,MONTO_CAPITAL,MONTO_INTERES,MONTO_MORA,MONTO_OTROS,
        MONTO_SEGURO,MONTO_RECARGOS FROM dbo.CRD_MOVIMIENTOS_CARTERA
        WHERE ID_CREDITO=? AND FECHA_OPERACION<'2026-10-20'
        ORDER BY FECHA_OPERACION,ID_CRD_MOVIMIENTO""",
    'history': """SELECT CAST(d.FECHA_OPERACION AS date) AS source_day,
        h.SALDO_INTERES,h.MONTO_DESEMBOLSADO,h.SALDO_PAGADO_CAPITAL,
        h.SALDO_PAGADO_INTERES,h.FECHA_ULTIMO_PAGOINT,h.CRD_CONGELADO,
        f.SALDO_CUENTA,f.TASA_INTERES,f.INT_PROV
        FROM dbo.CRD_HISTORICO_DIARIO h JOIN dbo.CIERRE_DIARIO d
          ON d.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
        LEFT JOIN dbo.FNC_PROVISIONES f ON f.ID_TIPO_PRODUCTO='3'
          AND f.REF_ID=h.ID_CREDITO AND f.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
        WHERE h.ID_CREDITO=? AND d.CIERRE='1'
          AND d.FECHA_OPERACION>=h.FECHA_OTORGAMIENTO
          AND d.FECHA_OPERACION<'2026-10-20' ORDER BY d.FECHA_OPERACION""",
}

def extract(destination):
    settings,_=guard()
    if destination.exists():
        raise ValueError('Refusing to overwrite a source evidence snapshot')
    output={}
    with source_connection(settings.source) as connection:
        for key in KEYS:
            output[key]={name:select_rows(connection,sql,(int(key),))
                for name,sql in SOURCE_QUERIES.items()}
    destination.write_text(json.dumps(output,indent=2,default=str))
    print(json.dumps({'source_keys':KEYS,'path':str(destination),
        'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}))

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()

def dec(x):
    return Decimal(str(x or 0))

def iso(x):
    return str(x)[:10]

def guard():
    s=load_settings('local')
    from urllib.parse import urlparse
    pg=urlparse(s.target.pg_url or '')
    if (s.target.tenant!='sandbox' or pg.path!='/fineract_sandbox'
            or pg.hostname not in ('127.0.0.1','localhost')):
        raise ValueError('Only local disposable fineract_sandbox is permitted')
    api=FineractApi(s.target)
    boundary=api.request('GET','accountingcutoff')
    if boundary.get('lifecycleState')!='ACTIVE' or boundary.get('cutoffDate')!=T:
        raise ValueError('Existing accounting boundary is not the frozen experiment boundary')
    return s,api

def product_payload(enabled):
    variant='on' if enabled else 'off'
    p={
        'name':f'PROOF {NAMESPACE} recalculation {variant}',
        'shortName':'RCA1' if enabled else 'RCA0',
        'externalId':f'PROOF:{NAMESPACE}:PRODUCT:{variant}',
        'description':'Isolated ordinary-interest experiment; no insurance, mora, or accounting',
        'numberingCode':'3S1' if enabled else '3R1','idTipoLinea':'001',
        'currencyCode':'USD','digitsAfterDecimal':2,'inMultiplesOf':0,'locale':'en',
        'principal':'565','minPrincipal':'1','maxPrincipal':'10000',
        'numberOfRepayments':75,'minNumberOfRepayments':1,'maxNumberOfRepayments':366,
        'repaymentEvery':1,'repaymentFrequencyType':0,
        'interestRatePerPeriod':str(Decimal(250)/12),'interestRateFrequencyType':2,
        'amortizationType':1,'interestType':0,'interestCalculationPeriodType':0,
        'transactionProcessingStrategyCode':'credesal-accrued-interest-first-strategy',
        'accountingRule':1,'daysInMonthType':1,'daysInYearType':1,
        'isInterestRecalculationEnabled':enabled,
        'loanScheduleType':'CUMULATIVE','loanScheduleProcessingType':'HORIZONTAL',
        'allowVariableInstallments':True,'minimumGap':1,'maximumGap':366,
        'canDefineInstallmentAmount':True,'charges':[],
        'allowAttributeOverrides':{'amortizationType':True,'interestType':True,
            'transactionProcessingStrategyCode':True,'interestCalculationPeriodType':True,
            'inArrearsTolerance':True,'repaymentEvery':True,'graceOnPrincipalAndInterestPayment':True,
            'graceOnArrearsAgeing':True},
    }
    if enabled:
        p.update({'interestRecalculationCompoundingMethod':0,'rescheduleStrategyMethod':1,
            'recalculationRestFrequencyType':2,'recalculationRestFrequencyInterval':1,
            'preClosureInterestCalculationStrategy':1,'isArrearsBasedOnOriginalSchedule':True})
    return p

def build(source_path):
    settings,api=guard()
    raw=json.loads(source_path.read_text())
    if tuple(raw)!=KEYS:
        raise ValueError('Wrong bounded source cohort')
    loans=[]
    for key,v in raw.items():
        if len(v['terms'])!=1 or v['history'][-1]['source_day']!=S:
            raise ValueError('Missing terms or final completed close')
        terms=v['terms'][0]
        client=api.find_client(terms['client_external_id'])
        if client is None:
            raise ValueError(f'Missing sandbox client for {key}')
        repayments=[m for m in v['movements'] if dec(m['MONTO_INTERES'])>0 or (
            dec(m['MONTO_CAPITAL'])>0 and m['transaction_code']!='00002')]
        if any(m['REVERSION'] not in (None,'','0') for m in repayments):
            raise ValueError('Reversal requires a different proof contract')
        for enabled in (False,True):
            variant='on' if enabled else 'off'
            external=f'PROOF:{NAMESPACE}-{variant}:ARISSTO:CRD:{key}'
            if _find_loan(api,external) is not None:
                raise ValueError('Plan requires fresh proof identities')
        loans.append({'source_key':key,'client_id':client['id'],
            'terms':{k:val for k,val in terms.items() if k!='client_external_id'},
            'schedule':v['schedule'],'repayments':repayments,'history':v['history']})
    doc={'kind':'paired-ordinary-interest-recalculation-v1','writer_revision':5,'namespace':NAMESPACE,
        'target_fingerprint':settings.target.fingerprint,'source_through_date':S,
        'fineract_starts':T,'run_mode':'isolated canary in existing target lifetime',
        'source_file_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'products':{'off':product_payload(False),'on':product_payload(True)},'loans':loans,
        'exclusions':['insurance','mora charges and payment portions','fees','opening interest alignment',
            'refinance predecessors; current loan life starts as standalone disbursement'],
        'primary_measure':'dated collectible schedule projection; dated prepayment quote is separate',
        'daily_measure':'snapshot after replaying only payments through source close, projected to S+1'}
    plan=hashlib.sha256(canonical(doc)).hexdigest()
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    dest=DIRECTORY/f'{plan}.json'
    if dest.exists() and dest.read_bytes()!=canonical(doc):
        raise RuntimeError('Immutable plan collision')
    dest.write_bytes(canonical(doc))
    print(json.dumps({'plan_id':plan,'source_keys':KEYS,'proof_loans':10,
        'target':'local sandbox','fingerprint':settings.target.fingerprint,
        'Arissto through':S,'Fineract starts':T,'path':str(dest)},indent=2))

def read_plan(plan):
    if len(plan)!=64 or any(c not in '0123456789abcdef' for c in plan):
        raise ValueError('Invalid plan ID')
    doc=json.loads((DIRECTORY/f'{plan}.json').read_text())
    if hashlib.sha256(canonical(doc)).hexdigest()!=plan:
        raise ValueError('Immutable plan checksum changed')
    return doc

def load_loan(api,external):
    loan=_find_loan(api,external)
    if loan is None or loan['externalId']!=external:
        raise ValueError('Proof identity missing or changed')
    return loan

REPAIR_INPUTS = (
    'fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/transactionprocessor/LoanRepaymentScheduleTransactionProcessor.java',
    'fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/transactionprocessor/impl/CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.java',
    'fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/loanschedule/domain/AbstractCumulativeLoanScheduleGenerator.java',
    'tools/arissto-sync/arissto_sync/loan_recalculation_canary.py',
)

def repair_input_hashes():
    checkout = ROOT.parents[1]
    return {p:hashlib.sha256((checkout/p).read_bytes()).hexdigest() for p in REPAIR_INPUTS}

def build_recovery(base_plan, attempt, from_recovery=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,23}', attempt):
        raise ValueError('Use a bounded retry attempt identity')
    base = read_plan(base_plan)
    settings,api = guard()
    if base['target_fingerprint'] != settings.target.fingerprint:
        raise ValueError('Target fingerprint changed')
    parent = from_recovery or base_plan
    if from_recovery and read_plan(from_recovery).get('base_plan_id') != base_plan:
        raise ValueError('Recovery parent belongs to another base plan')
    path = DIRECTORY/f'{parent}-result.json'
    prior = json.loads(path.read_text())
    pending = []
    for run in prior['runs']:
        if run.get('complete'):
            continue
        if run['variant'] != 'on' or run['source_key'] not in KEYS:
            raise ValueError('Only incomplete on copies may be retried')
        loan = load_loan(api,run['external_id'])
        if loan['id'] != run['loan_id'] or loan['status']['id'] != 300:
            raise ValueError('Proof identity or active state changed')
        ids = sorted(t['externalId'] for t in loan.get('transactions',[])
            if t['type']['id']==2 and not t.get('manuallyReversed'))
        pending.append({'source_key':run['source_key'],'variant':run['variant'],
            'loan_id':loan['id'],'external_id':run['external_id'],
            'baseline_repayment_external_ids':ids})
    if not pending:
        raise ValueError('No incomplete proof loans to retry')
    recovery = {'kind':'paired-ordinary-interest-recovery-v1',
        'base_plan_id':base_plan,'parent_result_id':parent,
        'baseline_result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'attempt':attempt,'target_fingerprint':settings.target.fingerprint,
        'source_through_date':S,'fineract_starts':T,'pending_loans':pending,
        'repair_input_hashes':repair_input_hashes(),
        'scope':'Continue the same proof copies; no products, loans, resets or opening adjustments'}
    identity = hashlib.sha256(canonical(recovery)).hexdigest()
    dest = DIRECTORY/f'{identity}.json'
    if dest.exists() and dest.read_bytes()!=canonical(recovery):
        raise ValueError('Immutable recovery plan collision')
    dest.write_bytes(canonical(recovery))
    print(json.dumps({'recovery_plan_id':identity,'base_plan_id':base_plan,
        'attempt':attempt,'pending_loans':pending,'target':'local sandbox',
        'Arissto through':S,'Fineract starts':T,'path':str(dest)},indent=2))

def apply(plan, recovery_id=None):
    doc=read_plan(plan);settings,api=guard()
    if doc['target_fingerprint']!=settings.target.fingerprint:
        raise ValueError('Target fingerprint changed')
    recovery = read_plan(recovery_id) if recovery_id else None
    if recovery and (recovery.get('kind')!='paired-ordinary-interest-recovery-v1'
            or recovery.get('base_plan_id')!=plan
            or recovery.get('target_fingerprint')!=settings.target.fingerprint
            or recovery.get('repair_input_hashes')!=repair_input_hashes()):
        raise ValueError('Recovery identity, target or repair inputs changed')
    result_path=DIRECTORY/f'{recovery_id or plan}-result.json'
    if recovery and not result_path.exists():
        parent_path=DIRECTORY/f"{recovery['parent_result_id']}-result.json"
        if hashlib.sha256(parent_path.read_bytes()).hexdigest()!=recovery['baseline_result_sha256']:
            raise ValueError('Baseline result changed')
        for expected in recovery['pending_loans']:
            loan=load_loan(api,expected['external_id'])
            ids=sorted(t['externalId'] for t in loan.get('transactions',[])
                if t['type']['id']==2 and not t.get('manuallyReversed'))
            if loan['id']!=expected['loan_id'] or ids!=expected['baseline_repayment_external_ids']:
                raise ValueError('Proof repayment baseline changed')
        result=json.loads(parent_path.read_text())
        result['recovery_plan_id']=recovery_id
        result['retry_attempt']=recovery['attempt']
    else:
        result=json.loads(result_path.read_text()) if result_path.exists() else {
            'plan_id':plan,'target_fingerprint':settings.target.fingerprint,'runs':[],'products':{}}
    def save():
        result_path.write_text(json.dumps(result,indent=2,default=str))
    for variant,payload in doc['products'].items():
        products=api.request('GET','loanproducts')
        found=[p for p in products if p.get('externalId')==payload['externalId']]
        if len(found)>1:
            raise RuntimeError('Duplicate proof product')
        if recovery and (len(found)!=1 or found[0]['id']!=result['products'][variant]):
            raise ValueError('Recovery must reuse the same proof products')
        product_id=found[0]['id'] if found else api.request('POST','loanproducts',payload,
            idempotency_key=f'{NAMESPACE}:{plan[:12]}:product:{variant}')['resourceId']
        result['products'][variant]=product_id;save()
    for source in doc['loans']:
      for variant in ('off','on'):
        key=source['source_key'];external=f'PROOF:{NAMESPACE}-{variant}:ARISSTO:CRD:{key}'
        existing=next((r for r in result['runs'] if r['source_key']==key and r['variant']==variant),None)
        if existing and existing.get('complete'):
            continue
        if recovery and not any(r['source_key']==key and r['variant']==variant for r in recovery['pending_loans']):
            raise ValueError('Pending loan is outside the frozen recovery scope')
        record=existing or {'source_key':key,'variant':variant,'external_id':external,'daily':[]}
        if not existing:result['runs'].append(record)
        save()
        try:
            terms=source['terms'];origin=iso(terms['FECHA_OTORGAMIENTO'])
            schedule=[{'number':int(p['NO_CUOTA']),'due_date':iso(p['FECHA_PAGO']),
                'principal':p['MONTO_CAPITAL'],'interest':p['MONTO_INTERES']} for p in source['schedule']]
            payload={'clientId':source['client_id'],'productId':result['products'][variant],
                'externalId':external,'principal':terms['MONTO_DESEMBOLSADO'],
                'loanTermFrequency':(date.fromisoformat(schedule[-1]['due_date'])-date.fromisoformat(origin)).days,
                'loanTermFrequencyType':0,'numberOfRepayments':len(schedule),
                'repaymentEvery':1,'repaymentFrequencyType':0,
                'interestRatePerPeriod':str(dec(terms['INTERES_MONTO_APROBADO'])/12),
                'interestRateFrequencyType':2,'interestType':0,'amortizationType':1,
                'interestCalculationPeriodType':0,
                'transactionProcessingStrategyCode':'credesal-accrued-interest-first-strategy',
                'loanType':'individual','submittedOnDate':origin,'expectedDisbursementDate':origin,
                'repaymentsStartingFromDate':schedule[0]['due_date'],
                'dateFormat':'yyyy-MM-dd','locale':'en','charges':[]}
            loan=_find_loan(api,external)
            if recovery and (loan is None or loan['id']!=record['loan_id'] or loan['status']['id']!=300):
                raise ValueError('Recovery must continue an existing active proof loan')
            if loan is None:
                loan_id=api.request('POST','loans',payload,idempotency_key=f'{NAMESPACE}:{key}:{variant}:create')['loanId']
                loan=load_loan(api,external)
            record['loan_id']=loan['id'];save()
            if loan['status']['id']==100:
                action={'external_id':external,'lifecycle':{'schedule':schedule}}
                loan=_ensure_source_exact_pending_schedule(api,loan,action,None)
                api.request('POST',f"loans/{loan['id']}",{'approvedOnDate':origin,
                    'dateFormat':'yyyy-MM-dd','locale':'en'},query={'command':'approve'},
                    idempotency_key=f'{NAMESPACE}:{key}:{variant}:approve')
                loan=load_loan(api,external)
            if loan['status']['id']==200:
                api.request('POST',f"loans/{loan['id']}",{'actualDisbursementDate':origin,
                    'transactionAmount':terms['MONTO_DESEMBOLSADO'],
                    'externalId':f'{external}:DISBURSE','dateFormat':'yyyy-MM-dd','locale':'en'},
                    query={'command':'sourceExactDisburse'},
                    idempotency_key=f'{NAMESPACE}:{key}:{variant}:disburse')
                loan=load_loan(api,external)
            if record.get('error'):record.pop('error')
            for h in source['history']:
                day=h['source_day']
                if any(r['source_day']==day for r in record['daily']):continue
                for m in source['repayments']:
                    if iso(m['FECHA_OPERACION'])!=day:continue
                    txid=f"{external}:MOV:{m['movement_id']}"
                    if not any(t.get('externalId')==txid for t in loan.get('transactions',[])):
                        api.request('POST',f"loans/{loan['id']}/transactions",{
                            'transactionDate':day,'transactionAmount':str(dec(m['MONTO_CAPITAL'])+dec(m['MONTO_INTERES'])),
                            'principalPortion':m['MONTO_CAPITAL'],'interestPortion':m['MONTO_INTERES'],
                            'feeChargesPortion':'0','penaltyChargesPortion':'0','externalId':txid,
                            'dateFormat':'yyyy-MM-dd','locale':'en'},query={'command':'sourceExactRepayment'},
                            idempotency_key=(('rc:'+hashlib.sha256(canonical([plan,key,variant,m['movement_id'],recovery['attempt']])).hexdigest()[:46])
                                if recovery else f'{NAMESPACE}:{key}:{variant}:{m["movement_id"]}'))
                        loan=load_loan(api,external)
                first_day=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
                quote=api.request('GET',f"loans/{loan['id']}/transactions/template",query={
                    'command':'prepayLoan','transactionDate':first_day,'dateFormat':'yyyy-MM-dd','locale':'en'})
                native=native_interest_as_of(loan,date.fromisoformat(first_day))
                actual_principal=dec((loan.get('summary') or {}).get('principalOutstanding'))
                expected_principal=dec(h['MONTO_DESEMBOLSADO'])-dec(h['SALDO_PAGADO_CAPITAL'])
                record['daily'].append({'source_day':day,'native_date':first_day,
                    'source_interest':h['SALDO_INTERES'],'schedule_projection':str(native),
                    'projection_difference':str(native-dec(h['SALDO_INTERES'])),
                    'prepayment_interest':str(quote.get('interestPortion')),
                    'quote_difference':str(dec(quote.get('interestPortion'))-dec(h['SALDO_INTERES'])),
                    'principal_difference':str(actual_principal-expected_principal),
                    'schedule':loan.get('repaymentSchedule'),
                    'transactions':[{k:t.get(k) for k in ('id','externalId','date','type','amount',
                        'principalPortion','interestPortion','manuallyReversed')} for t in loan.get('transactions',[])]})
                save()
            loan=load_loan(api,external)
            record['final_summary']=loan.get('summary');record['charges']=loan.get('charges',[])
            record['initial_source_schedule_differences_at_end']=_loan_schedule_differences(schedule,loan.get('repaymentSchedule') or {})
            record['complete']=True;save()
            print(json.dumps({'source':key,'variant':variant,'loan':loan['id'],'days':len(record['daily']),
                'final':{k:v for k,v in record['daily'][-1].items() if k not in ('schedule','transactions')} }),flush=True)
        except Exception as exc:
            record['error']=str(exc);save()
            print(json.dumps({'source':key,'variant':variant,'error':str(exc)}),flush=True)
    with postgres_connection(settings.target.pg_url) as conn:
        ids=[r['loan_id'] for r in result['runs'] if r.get('loan_id')]
        result['linked_gl_rows']=conn.execute('SELECT COUNT(*) FROM acc_gl_journal_entry WHERE loan_transaction_id IN (SELECT id FROM m_loan_transaction WHERE loan_id=ANY(%s))',(ids,)).fetchone()[0]
    save()
    print(json.dumps({'result_path':str(result_path),'complete':sum(bool(r.get('complete')) for r in result['runs']),
        'linked_gl_rows':result['linked_gl_rows']}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('extract');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('plan');p.add_argument('--source',type=Path,required=True)
    p=sub.add_parser('apply');p.add_argument('--plan',required=True)
    p=sub.add_parser('recovery-plan');p.add_argument('--plan',required=True);p.add_argument('--attempt',required=True);p.add_argument('--from-recovery')
    p=sub.add_parser('recover');p.add_argument('--recovery-plan',required=True)
    args=parser.parse_args()
    if args.command=='extract':extract(args.output)
    elif args.command=='plan':build(args.source)
    elif args.command=='recovery-plan':build_recovery(args.plan,args.attempt,args.from_recovery)
    elif args.command=='recover':
        recovery=read_plan(args.recovery_plan)
        apply(recovery['base_plan_id'],args.recovery_plan)
    else:apply(args.plan)
