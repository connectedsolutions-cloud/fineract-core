import json
from pathlib import Path
from decimal import Decimal as D
from datetime import date
root=Path('/private/tmp/servicing-off-oct28');r=json.loads((root/'result.json').read_text());db=json.loads((root/'persisted.json').read_text());checks=[]
def check(name,expected,actual):checks.append({'name':name,'expected':expected,'actual':actual,'pass':expected==actual})
def amount(v):return format(D(str(v)),'.2f')
def row(day,name):return next(x for x in r['days']+r['followup']+r['positive_mora_pause'] if x['day']==day)['loans'][name]['summary']
for group in ('days','followup','positive_mora_pause'):
 for day in r[group]:
  for name,x in day['loans'].items():check('recalculation-disabled:'+day['day']+':'+name,False,x['recalculation'])
for name,when,total in [('early','2026-10-28','512.00'),('ontime','2026-10-30','514.00'),('late','2026-11-01','516.00')]:
 s=row(when,name);check(name+':principal-after-500-principal-payment','500.00',amount(s['principalOutstanding']));check(name+':interest-allocation',amount(D(total)-500),amount(s['interestPaid']))
for day in r['days']+r['followup']:
 n=(date.fromisoformat(day['day'])-date(2026,10,26)).days
 check('unpaid-control:'+day['day'],amount(D(10)+n),amount(day['loans']['control']['summary']['interestOutstanding']))
for day in ['2026-11-08','2026-11-09','2026-11-10','2026-11-11','2026-11-12']:
 n=(date.fromisoformat(day)-date(2026,10,26)).days
 paused=max(0,min((date.fromisoformat(day)-date(2026,11,8)).days,2))
 check('interest-pause-resume:'+day,amount(D(10)+n-paused),amount(row(day,'interest-pause')['interestOutstanding']))
for day in r['positive_mora_pause']:
 expected={'2026-11-13':'1.01','2026-11-14':'1.01','2026-11-15':'1.01','2026-11-16':'1.12','2026-11-17':'1.23'}[day['day']]
 check('positive-mora-pause-resume:'+day['day'],expected,amount(day['loans']['mora-pause']['summary']['penaltyChargesOutstanding']))
check('mora-waiver-immediate','0.00',amount(r['mora_waiver_immediate']['summary']['penaltyChargesOutstanding']))
for day in r['followup']:
 check('interest-waiver-retained:'+day['day'],'5.00',amount(day['loans']['interest-waiver']['summary']['interestWaived']))
 check('mora-waiver-retained:'+day['day'],'0.51',amount(day['loans']['mora-waiver']['summary']['penaltyChargesWaived']))
for name in ['interest-waiver','mora-waiver']:
 s=row('2026-11-09',name);expected=D(10)+14-D(str(s['interestPaid']))-D(str(s['interestWaived']))
 check('later-payment-no-interest-duplication:'+name,amount(expected),amount(s['interestOutstanding']))
check('interest-pause-across-future-installment',True,next(e['ok'] for e in r['events'] if e['key']=='interest-pause'))
for name,x in db.items():
 check('persisted-recalculation-disabled:'+name,False,x['stored_loan'][0]);check('no-pre-boundary-gl:'+name,0,x['gl_count_income_and_historical_count'][2])
for k in ['controls_restored','scheduler_still_paused','protected_loans_unchanged','repeat_cob_unchanged','repeat_cob_gl_unchanged']:check(k,True,r[k])
check('unpaid-control-native-income','22.00',amount(db['control']['gl_count_income_and_historical_count'][1]));check('paused-interest-native-income','15.00',amount(db['interest-pause']['gl_count_income_and_historical_count'][1]))
out={'observed_on':'2026-10-28','acceptance':False,'scope':'Synthetic migration-baseline loans in disposable local sandbox; standard recalculation false throughout. No Arissto parity requirement.','Arissto through':'2026-10-26','Fineract starts':'2026-10-27','namespace':r['namespace'],'loans':{k:v['id'] for k,v in r['loans'].items()},'successful_scoped_cob_closes':sum(len(x['loans']) for group in ['days','followup','positive_mora_pause'] for x in r[group]),'checks':checks,'failed_checks':[x for x in checks if not x['pass']],'events':[{'key':e['key'],'ok':e.get('ok',True),'error':e.get('error')} for e in r['events']],'persisted':db,'limitation':'Checks are bounded synthetic servicing acceptance. Mora expected frozen/resume amounts check new-day behavior, not a full portfolio mora pricing model. Source history replay, refinancing, other strategies and backdated reversals are outside scope.'}
(root/'checks.json').write_text(json.dumps(out,indent=2));print(json.dumps({'checks':len(checks),'failed':out['failed_checks'],'scoped_cob_closes':out['successful_scoped_cob_closes']},indent=2))
