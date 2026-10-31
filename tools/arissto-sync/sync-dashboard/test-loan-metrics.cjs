const test = require('node:test');
const assert = require('node:assert/strict');
const { loanMetricPanel } = require('./loan-metrics.js');
const fixture = () => ({ active_loans: 1, matched: 8, expected_checks: 8, mismatched: 0, complete: true,
  metrics: { insuranceOutstanding: { checked: 1, matched: 1, mismatched: 0 } },
  insurance: [{ source_key: 'loan:1', insuranceOwed: '2.00', futureInsurance: '4.00', scheduledInsurance: '6.00' }],
  reference_details: { active_count: 1000, inactive_count: 20, groups: [{classification:'expected',kind:'schedule_due_date',count:1000}] },
  integrity_mismatch_count: 0 });
test('metrics lead, expected references are collapsed and separate', () => {
  const html = loanMetricPanel(fixture());
  assert.match(html, /8 \/ 8 values match/);assert.match(html, /0 metric mismatches/);
  assert.match(html, /<details><summary>Reference details/);assert.doesNotMatch(html, /<details open/);
  assert.ok(html.indexOf('eight handover metrics') < html.indexOf('Reference details'));
  assert.match(html, /Insurance owed/);assert.match(html, /Future insurance/);assert.match(html, /2.00/);assert.match(html, /4.00/);
});
test('missing insurance split is not zero and incomplete verification is not success', () => {
  const f=fixture();f.complete=false;f.insurance[0].futureInsurance=null;
  const html=loanMetricPanel(f);assert.match(html,/Verification incomplete/);assert.match(html,/Not recorded/);
});
test('untrusted reference labels and source IDs are escaped', () => {
  const f=fixture();f.insurance[0].source_key='<script>bad</script>';
  f.reference_details.groups[0].classification='<img src=x>';
  const html=loanMetricPanel(f);assert.doesNotMatch(html,/<script>|<img/);assert.match(html,/&lt;script&gt;/);
  assert.equal(loanMetricPanel(null),'');
});
