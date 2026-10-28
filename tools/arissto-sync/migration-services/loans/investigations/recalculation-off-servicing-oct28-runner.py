import json,hashlib,sys,copy,psycopg
from pathlib import Path
from datetime import date,timedelta,datetime,timezone
from decimal import Decimal as D, ROUND_HALF_EVEN
from urllib.parse import urlparse
from arissto_sync.config import load_settings
from arissto_sync.connections import FineractApi,postgres_connection
from arissto_sync.loan_recalculation_canary import product_payload
NS='servicing-off-oct28'; ROOT=Path('/private/tmp')/NS;ROOT.mkdir(exist_ok=True)
OUT=ROOT/'result.json'; PLAN=ROOT/'plan.json'
s=load_settings('local');u=urlparse(s.target.pg_url or '')
assert s.target.tenant=='sandbox' and u.hostname in ('127.0.0.1','localhost') and u.path=='/fineract_sandbox'
a=FineractApi(s.target);assert a.request('GET','accountingcutoff')['cutoffDate']=='2026-10-27';assert not a.request('GET','scheduler')['active']
r=json.loads(OUT.read_text()) if OUT.exists() else {'namespace':NS,'fingerprint':s.target.fingerprint,'products':{},'loans':{},'events':[],'days':[],'errors':[]}
def save():OUT.write_text(json.dumps(r,indent=2,default=str))
def call(method,path,body=None,command=None):return a.request(method,path,body,query={'command':command} if command else None)
def get(lid):return a.request('GET',f'loans/{lid}',query={'associations':'all'})
def snap(lid):
 l=get(lid);return {'id':lid,'recalculation':l['isInterestRecalculationEnabled'],'summary':l['summary'],'lastClosedBusinessDate':l.get('lastClosedBusinessDate'),'transactions':[{k:t.get(k) for k in ['id','type','date','amount','principalPortion','interestPortion','penaltyChargesPortion','reversed']} for t in l.get('transactions',[])],'charges':[{k:c.get(k) for k in ['id','chargeId','name','externalId','amount','amountOutstanding','amountPaid','amountWaived','dueDate','penalty']} for c in l.get('charges',[])]}
def clock(business,cob=None):
 call('POST','businessdate',{'type':'BUSINESS_DATE','date':business,'dateFormat':'yyyy-MM-dd','locale':'en'})
 if cob:call('POST','businessdate',{'type':'COB_DATE','date':cob,'dateFormat':'yyyy-MM-dd','locale':'en'})
def protect():
 with postgres_connection(s.target.pg_url) as c:
  return str(c.execute("SELECT count(*),md5(COALESCE(string_agg(row_to_json(l)::text,'' ORDER BY id),'')) FROM m_loan l WHERE external_id IS NULL OR external_id NOT LIKE %s",(f'PROOF:{NS}:%',)).fetchone())
if sys.argv[1]=='plan':
 p=product_payload(False);p.update(name='PROOF servicing off Oct28',shortName='SO28',numberingCode='3V1',externalId=f'PROOF:{NS}:PRODUCT',principal='1000',interestRatePerPeriod=str(D('36.5')/12),numberOfRepayments=2,repaymentEvery=7,accountingRule=3)
 source=a.request('GET','loanproducts/1')
 for k,v in source['accountingMappings'].items():p[k+'Id']=v['id']
 p['charges']=[]
 plan={'namespace':NS,'target':'local sandbox','fingerprint':s.target.fingerprint,'Arissto through':'2026-10-26','Fineract starts':'2026-10-27','scope':'8 fresh synthetic namespaced loans with API-installed migration baselines; no canonical loans or source reads/writes. Scoped inline COB only; scheduler stays paused.','product':p,'scenarios':['early','ontime','late','control','interest-pause','mora-pause','interest-waiver','mora-waiver'],'firstDue':'2026-10-30','paymentDates':{'early':'2026-10-28','ontime':'2026-10-30','late':'2026-11-01'},'principalPayment':'500.00','initialInterest':'10.00','initialPrincipal':'1000.00','initialDuePrincipalForMora':'200.00','days':[(date(2026,10,27)+timedelta(days=i)).isoformat() for i in range(12)]}
 PLAN.write_text(json.dumps(plan,indent=2));print(json.dumps({'plan':str(PLAN),'sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'target':plan['target'],'Arissto through':plan['Arissto through'],'Fineract starts':plan['Fineract starts'],'scenarios':plan['scenarios']}));sys.exit()
plan=json.loads(PLAN.read_text())
prior=a.request('GET','businessdate');enabled=a.request('GET','configurations/44')['enabled']
if 'original_controls' not in r:r['original_controls']={'enabled':enabled,'dates':prior,'protected':protect()};save()
try:
 call('PUT','configurations/44',{'enabled':True});clock('2026-10-27','2026-10-26')
 if sys.argv[1]=='setup':
  for variant in ('plain','mora'):
   if variant not in r['products']:
    p=copy.deepcopy(plan['product']);p['name']+=' '+variant;p['shortName']='SOP8' if variant=='plain' else 'SOM8';p['numberingCode']='3V1' if variant=='plain' else '3W1';p['externalId']+=':'+variant
    if variant=='mora':p['charges']=[{'id':4}]
    r['products'][variant]=call('POST','loanproducts',p)['resourceId'];save()
  for i,name in enumerate(plan['scenarios']):
   if name in r['loans']:continue
   mora=name in ('mora-pause','mora-waiver');ext=f'PROOF:{NS}:ARISSTO:CRD:{900000+i}'
   p={'clientId':282,'productId':r['products']['mora' if mora else 'plain'],'externalId':ext,'principal':'1000','loanTermFrequency':14,'loanTermFrequencyType':0,'numberOfRepayments':2,'repaymentEvery':7,'repaymentFrequencyType':0,'interestRatePerPeriod':str(D('36.5')/12),'interestRateFrequencyType':2,'interestType':0,'amortizationType':1,'interestCalculationPeriodType':0,'transactionProcessingStrategyCode':'credesal-accrued-interest-first-strategy','loanType':'individual','submittedOnDate':'2026-10-26','expectedDisbursementDate':'2026-10-26','repaymentsStartingFromDate':'2026-10-30','dateFormat':'yyyy-MM-dd','locale':'en','charges':[]}
   lid=call('POST','loans',p)['loanId'];r['loans'][name]={'id':lid,'externalId':ext,'setupComplete':False};save()
   call('POST',f'loans/{lid}',{'approvedOnDate':'2026-10-26','locale':'en','dateFormat':'yyyy-MM-dd'},'approve')
   call('POST',f'loans/{lid}',{'actualDisbursementDate':'2026-10-26','transactionAmount':'1000','externalId':ext+':DISBURSE','locale':'en','dateFormat':'yyyy-MM-dd'},'sourceExactDisburse')
   query={'cutoffDate':'2026-10-27','insuranceChargeId':2,'recurringInsuranceChargeId':3}
   obs=a.request('GET',f'loans/{lid}/migration-metrics',query=query)
   targets={'paidPrincipal':'0.00','outstandingPrincipal':'1000.00','paidInterest':'0.00','accruedInterest':'10.00','duePrincipal':'200.00' if mora else '0.00','mora':'0.00','insurancePaid':'0.00','insuranceOutstanding':'0.00'}
   body=dict(query,penaltyChargeId=1,sourceSystem='ARISSTO',sourceLoanExternalId=ext,sourceObservedAt=datetime.now(timezone.utc).isoformat(),requestId=NS+':'+name,expected=obs['metrics'],targets=targets)
   call('POST',f'loans/{lid}/migration-metrics',body)
   r['loans'][name].update(setupComplete=True,opening=snap(lid));save();print('created',name,lid,flush=True)
 elif sys.argv[1]=='run':
  assert all(x['setupComplete'] for x in r['loans'].values())
  def event(key,fn):
   if key in [x['key'] for x in r['events']]:return

   try:
    response=fn();r['events'].append({'key':key,'response':response,'ok':True})
   except Exception as e:
    r['events'].append({'key':key,'ok':False,'error':str(e)[:1800]});print('EVENT_FAILED',key,str(e)[:300],flush=True)
   save()
  lid=r['loans']['interest-pause']['id']
  event('interest-pause',lambda:call('POST',f'loans/{lid}/interest-pauses',{'startDate':'2026-10-29','endDate':'2026-10-31','dateFormat':'yyyy-MM-dd','locale':'en'}))
  for day in plan['days']:
   if any(x['day']==day for x in r['days']):continue
   clock(day,(date.fromisoformat(day)-timedelta(days=1)).isoformat())
   for name,when in plan['paymentDates'].items():
    if day==when:
     lid=r['loans'][name]['id']; elapsed=(date.fromisoformat(day)-date(2026,10,26)).days
     amount=str(D('510')+elapsed)
     event(name+'-repayment',lambda lid=lid,amount=amount:call('POST',f'loans/{lid}/transactions',{'transactionDate':day,'transactionAmount':amount,'externalId':NS+':'+name+':PAY','dateFormat':'yyyy-MM-dd','locale':'en'},'repayment'))
   if day=='2026-10-29':
    lid=r['loans']['mora-pause']['id'];event('mora-freeze',lambda:call('POST',f'loans/{lid}',{'effectiveDate':day,'reason':'Isolated off-mode servicing test','dateFormat':'yyyy-MM-dd','locale':'en'},'freezeMora'))
   if day=='2026-11-01':
    lid=r['loans']['mora-pause']['id'];event('mora-unfreeze',lambda:call('POST',f'loans/{lid}',{'effectiveDate':day,'dateFormat':'yyyy-MM-dd','locale':'en'},'unfreezeMora'))
   if day=='2026-10-30':
    lid=r['loans']['interest-waiver']['id'];event('interest-waiver',lambda:call('POST',f'loans/{lid}/transactions',{'transactionDate':day,'transactionAmount':'5.00','externalId':NS+':IW','dateFormat':'yyyy-MM-dd','locale':'en'},'waiveinterest'))
    lid=r['loans']['mora-waiver']['id'];charges=[c for c in get(lid).get('charges',[]) if c.get('penalty') and D(str(c.get('amountOutstanding',0)))>0]
    for c in charges:
     event('mora-waiver-'+str(c['id']),lambda c=c:call('POST',f"loans/{lid}/charges/{c['id']}",{},'waive'))
   clock((date.fromisoformat(day)+timedelta(days=1)).isoformat(),day)

   for name,x in r['loans'].items():
    try:call('POST','jobs/LOAN_COB/inline',{'loanIds':[x['id']]})
    except Exception as e:
     r['errors'].append({'phase':'cob','day':day,'scenario':name,'message':str(e)[:1800]});save();print('COB_FAILED',day,name,str(e)[:250],flush=True)
   observations={name:snap(x['id']) for name,x in r['loans'].items()}
   r['days'].append({'day':day,'loans':observations});save()
   print(json.dumps({'day':day,'loans':{name:{k:x['summary'].get(k) for k in ['principalOutstanding','interestOutstanding','interestPaid','interestWaived','penaltyChargesOutstanding','penaltyChargesWaived']} for name,x in observations.items()}}),flush=True)
 elif sys.argv[1]=='followup':
  r.setdefault('followup',[])
  clock('2026-11-08','2026-11-07')
  def attempt(key,fn):
   if key in [x['key'] for x in r['events']]:return
   try:r['events'].append({'key':key,'ok':True,'response':fn()})
   except Exception as e:r['events'].append({'key':key,'ok':False,'error':str(e)[:1800]})
   save()
  lid=r['loans']['interest-pause']['id']
  attempt('interest-pause-after-final-due',lambda:call('POST',f'loans/{lid}/interest-pauses',{'startDate':'2026-11-09','endDate':'2026-11-10','dateFormat':'yyyy-MM-dd','locale':'en'}))
  lid=r['loans']['mora-waiver']['id'];before=snap(lid)
  charges=[c for c in get(lid).get('charges',[]) if c.get('penalty') and D(str(c.get('amountOutstanding',0)))>0]
  r['mora_waiver_before']=before;save()
  for c in charges:
   attempt('mora-waiver-'+str(c['id']),lambda c=c:call('POST',f"loans/{lid}/charges/{c['id']}",{},'waive'))
  r['mora_waiver_immediate']=snap(lid);save()
  for offset in range(5):
   day=(date(2026,11,8)+timedelta(days=offset)).isoformat()
   if any(x['day']==day for x in r['followup']):continue
   clock(day,(date.fromisoformat(day)-timedelta(days=1)).isoformat())
   if day=='2026-11-09':
    for name in ('interest-waiver','mora-waiver'):
     lid=r['loans'][name]['id']
     attempt(name+'-later-payment',lambda lid=lid,name=name:call('POST',f'loans/{lid}/transactions',{'transactionDate':day,'transactionAmount':'1.00','externalId':NS+':'+name+':AFTER','dateFormat':'yyyy-MM-dd','locale':'en'},'repayment'))
   clock((date.fromisoformat(day)+timedelta(days=1)).isoformat(),day)
   for name,x in r['loans'].items():
    try:call('POST','jobs/LOAN_COB/inline',{'loanIds':[x['id']]})
    except Exception as e:r['errors'].append({'phase':'followup-cob','day':day,'scenario':name,'message':str(e)[:1800]})
   obs={name:snap(x['id']) for name,x in r['loans'].items()};r['followup'].append({'day':day,'loans':obs});save()
   print(json.dumps({'day':day,'loans':{name:{k:x['summary'].get(k) for k in ['principalOutstanding','interestOutstanding','interestPaid','interestWaived','penaltyChargesOutstanding','penaltyChargesWaived']} for name,x in obs.items() if name in ('interest-pause','mora-pause','interest-waiver','mora-waiver')}}),flush=True)
  ids=[x['id'] for x in r['loans'].values()]
  def glstate():
   with postgres_connection(s.target.pg_url) as c:
    return str(c.execute('SELECT count(*),md5(COALESCE(string_agg(row_to_json(j)::text,\'\' ORDER BY j.id),\'\')) FROM acc_gl_journal_entry j JOIN m_loan_transaction t ON t.id=j.loan_transaction_id WHERE t.loan_id=ANY(%s)',(ids,)).fetchone())
  pre={name:snap(x['id']) for name,x in r['loans'].items()};gl=glstate()
  for lid in ids:call('POST','jobs/LOAN_COB/inline',{'loanIds':[lid]})
  r['repeat_cob_unchanged']=pre=={name:snap(x['id']) for name,x in r['loans'].items()};r['repeat_cob_gl_unchanged']=gl==glstate();save()

except Exception as e:
 r['errors'].append({'phase':sys.argv[1],'type':type(e).__name__,'message':str(e)[:1800]});save();raise
finally:
 prior=r['original_controls']['dates'];enabled=r['original_controls']['enabled']
 for saved in prior:
  raw=saved['date'];when=date(*raw).isoformat() if isinstance(raw,list) else raw
  call('POST','businessdate',{'type':saved['type'],'date':when,'dateFormat':'yyyy-MM-dd','locale':'en'})
 if not prior:
  clock('2026-10-28','2026-10-27')
 call('PUT','configurations/44',{'enabled':enabled})
 if not prior:
  # Restore only the two configuration rows created by this test; no financial SQL writes.
  with psycopg.connect(s.target.pg_url) as c:
   rows=c.execute('SELECT type,date FROM m_business_date').fetchall()
   assert sorted((str(x[0]),str(x[1])) for x in rows)==[('BUSINESS_DATE','2026-10-28'),('COB_DATE','2026-10-27')]
   c.execute("DELETE FROM m_business_date WHERE (type='BUSINESS_DATE' AND date='2026-10-28') OR (type='COB_DATE' AND date='2026-10-27')")
   c.commit()
 r['controls_restored']=a.request('GET','configurations/44')['enabled']==enabled and a.request('GET','businessdate')==prior
 r['scheduler_still_paused']=not a.request('GET','scheduler')['active'];r['protected_loans_unchanged']=protect()==r['original_controls']['protected'];save()
 print(json.dumps({k:r[k] for k in ['controls_restored','scheduler_still_paused','protected_loans_unchanged']}),flush=True)
