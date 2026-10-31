/* Pure rendering: financial metrics stay separate from historical references. */
(function (root) {
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const names = { paidPrincipal: "Paid principal", outstandingPrincipal: "Outstanding principal",
    paidInterest: "Paid interest", accruedInterest: "Accrued interest", duePrincipal: "Due principal",
    mora: "Accrued mora", insurancePaid: "Insurance paid", insuranceOutstanding: "Insurance owed at handover" };
  function loanMetricPanel(report) {
    if (!report) return "";
    const references = report.reference_details || {};
    const insurance = report.insurance || [];
    const available = (value) => value == null ? "Not recorded" : escape(value);
    return `<section class="section loan-metric-report">
      <div class="section-head"><div><p class="eyebrow">Active loans · eight handover metrics</p>
        <h3>${escape(report.active_loans)} active loans · ${escape(report.matched)} / ${escape(report.expected_checks)} values match</h3></div>
        <span class="count-pill">${report.complete ? escape(report.mismatched) + " metric mismatches" : "Verification incomplete"}</span></div>
      <p>Recorded handover verification. Later Fineract activity belongs in the native operational reports.</p>
      <div class="table-scroll"><table><thead><tr><th>Metric</th><th>Checked</th><th>Matched</th><th>Mismatched</th></tr></thead><tbody>
        ${Object.entries(report.metrics || {}).map(([key,v]) => `<tr><td>${escape(names[key] || key)}</td><td>${escape(v.checked)}</td><td>${escape(v.matched)}</td><td>${escape(v.mismatched)}</td></tr>`).join("")}
      </tbody></table></div>
      <details><summary>Insurance owed and future scheduled insurance</summary>
        <p>Insurance owed excludes future premiums. Unknown values are not zero.</p>
        ${insurance.length ? `<div class="table-scroll"><table><thead><tr><th>Source loan</th><th>Insurance owed</th><th>Future insurance</th><th>Scheduled insurance total</th></tr></thead><tbody>
          ${insurance.map((row) => `<tr><td>${escape(row.source_key)}</td><td>${available(row.insuranceOwed)}</td><td>${available(row.futureInsurance)}</td><td>${available(row.scheduledInsurance)}</td></tr>`).join("")}
        </tbody></table></div>` : "<p>This older run did not record the insurance split. Native operational reports show it separately.</p>"}
      </details>
      <details><summary>Reference details · ${escape(references.active_count || 0)} active schedule/charge rows · ${escape(references.inactive_count || 0)} inactive rows</summary>
        <p>These references do not add financial metric failures. Other integrity mismatches: ${escape(report.integrity_mismatch_count || 0)}.</p>
        <div class="table-scroll"><table><thead><tr><th>Reference classification</th><th>Field</th><th>Rows</th></tr></thead><tbody>
          ${(references.groups || []).map((row) => `<tr><td>${escape(row.classification)}</td><td>${escape(row.kind)}</td><td>${escape(row.count)}</td></tr>`).join("")}
        </tbody></table></div>
      </details></section>`;
  }
  root.loanMetricPanel = loanMetricPanel;
  if (typeof module !== "undefined") module.exports = { loanMetricPanel };
})(typeof window !== "undefined" ? window : globalThis);
