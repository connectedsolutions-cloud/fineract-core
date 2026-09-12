/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
package org.apache.fineract.accounting.reporting;

import java.math.BigDecimal;
import java.sql.Types;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class CredesalFinancialReportServiceImpl implements CredesalFinancialReportService {

    private static final String PERMISSION = "READ_CREDESAL_FINANCIAL_REPORTS";
    private static final Set<String> REPORT_TYPES = Set.of("general-ledger", "trial-balance", "balance-sheet", "income-statement");
    private static final LocalDate LEDGER_ORIGIN = LocalDate.of(2022, 11, 18);

    private static final String PRESENTATION_METADATA_SQL = """
            SELECT MIN(presentation_version) AS presentation_version,
                   MIN(source_snapshot_sha256) AS source_snapshot_sha256,
                   COUNT(DISTINCT presentation_version) AS version_count,
                   COUNT(DISTINCT source_snapshot_sha256) AS hash_count
              FROM credesal_gl_account_presentation
            """;

    private static final String DIMENSION_INTEGRITY_SQL = """
            SELECT COUNT(*)
             FROM acc_gl_journal_entry journal_entry
              JOIN m_office office ON office.id = journal_entry.office_id
             WHERE journal_entry.entry_date BETWEEN :fromDate AND :toDate
               AND (journal_entry.dimensions IS NULL
                    OR jsonb_typeof(journal_entry.dimensions -> 'office') <> 'string'
                    OR journal_entry.dimensions ->> 'office' IS DISTINCT FROM office.external_id)
            """;

    private static final String GENERAL_LEDGER_SQL = """
            SELECT journal_entry.id AS journal_entry_id,
                   TO_CHAR(journal_entry.entry_date, 'YYYY-MM-DD') AS entry_date,
                   journal_entry.transaction_id,
                   journal_entry.ref_num,
                   account.id AS gl_account_id,
                   account.gl_code,
                   account.name AS gl_account_name,
                   journal_entry.dimensions ->> 'office' AS office_external_id,
                   CASE WHEN journal_entry.type_enum = 2 THEN journal_entry.amount ELSE 0.00 END AS debit,
                   CASE WHEN journal_entry.type_enum = 1 THEN journal_entry.amount ELSE 0.00 END AS credit,
                   journal_entry.description,
                   provenance_line.source_line_sequence
              FROM acc_gl_journal_entry journal_entry
              JOIN acc_gl_account account ON account.id = journal_entry.account_id
              LEFT JOIN credesal_arissto_gl_journal_line provenance_line
                     ON provenance_line.target_journal_entry_id = journal_entry.id
             WHERE journal_entry.entry_date BETWEEN :fromDate AND :toDate
               AND (:officeExternalId IS NULL OR journal_entry.dimensions ->> 'office' = :officeExternalId)
             ORDER BY journal_entry.entry_date, journal_entry.transaction_id,
                      provenance_line.source_line_sequence NULLS LAST, journal_entry.id
            """;

    private static final String PRESENTED_REPORT_SQL = """
            WITH RECURSIVE report_tree AS (
                SELECT presentation.gl_account_id AS report_account_id,
                       presentation.source_gl_code,
                       presentation.source_name,
                       presentation.classifier_code,
                       presentation.classifier_name,
                       presentation.trial_balance_group,
                       presentation.trial_balance_order,
                       presentation.income_statement_order,
                       presentation.account_order,
                       presentation.balance_nature,
                       account.id AS descendant_account_id
                  FROM credesal_gl_account_presentation presentation
                  JOIN acc_gl_account account ON account.id = presentation.gl_account_id
                 WHERE (:reportType = 'trial-balance' AND presentation.trial_balance_selected)
                    OR (:reportType = 'balance-sheet' AND presentation.balance_sheet_selected)
                    OR (:reportType = 'income-statement'
                        AND presentation.trial_balance_selected
                        AND NOT presentation.balance_sheet_selected
                        AND presentation.classifier_code IN ('004', '005'))
                UNION ALL
                SELECT tree.report_account_id, tree.source_gl_code, tree.source_name,
                       tree.classifier_code, tree.classifier_name, tree.trial_balance_group,
                       tree.trial_balance_order, tree.income_statement_order,
                       tree.account_order, tree.balance_nature, child.id
                  FROM report_tree tree
                  JOIN acc_gl_account child ON child.parent_id = tree.descendant_account_id
            ), scoped_entries AS (
                SELECT journal_entry.*,
                       EXISTS (
                           SELECT 1 FROM credesal_arissto_gl_journal provenance
                            WHERE provenance.target_transaction_id = journal_entry.transaction_id
                              AND provenance.source_journal_type = '003'
                              AND provenance.source_journal_date BETWEEN :financialYearStart AND :toDate
                       ) AS current_annual_closing
                  FROM acc_gl_journal_entry journal_entry
                 WHERE journal_entry.entry_date <= :toDate
                   AND (:officeExternalId IS NULL OR journal_entry.dimensions ->> 'office' = :officeExternalId)
            ), report_amounts AS (
                SELECT tree.report_account_id, tree.source_gl_code, tree.source_name,
                       tree.classifier_code, tree.classifier_name, tree.trial_balance_group,
                       tree.trial_balance_order, tree.income_statement_order,
                       tree.account_order, tree.balance_nature,
                       SUM(CASE WHEN entry.entry_date < :fromDate AND entry.type_enum = 2 THEN entry.amount ELSE 0.00 END) AS opening_debit,
                       SUM(CASE WHEN entry.entry_date < :fromDate AND entry.type_enum = 1 THEN entry.amount ELSE 0.00 END) AS opening_credit,
                       SUM(CASE WHEN entry.entry_date BETWEEN :fromDate AND :toDate AND entry.type_enum = 2 THEN entry.amount ELSE 0.00 END) AS period_debit,
                       SUM(CASE WHEN entry.entry_date BETWEEN :fromDate AND :toDate AND entry.type_enum = 1 THEN entry.amount ELSE 0.00 END) AS period_credit,
                       SUM(CASE WHEN entry.entry_date <= :toDate AND entry.type_enum = 2 THEN entry.amount ELSE 0.00 END) AS closing_debit,
                       SUM(CASE WHEN entry.entry_date <= :toDate AND entry.type_enum = 1 THEN entry.amount ELSE 0.00 END) AS closing_credit
                  FROM report_tree tree
                  LEFT JOIN scoped_entries entry ON entry.account_id = tree.descendant_account_id
                   AND (NOT :excludeAnnualClosing
                        OR tree.classifier_code NOT IN ('004', '005')
                        OR NOT entry.current_annual_closing)
                 GROUP BY tree.report_account_id, tree.source_gl_code, tree.source_name,
                          tree.classifier_code, tree.classifier_name, tree.trial_balance_group,
                          tree.trial_balance_order, tree.income_statement_order,
                          tree.account_order, tree.balance_nature
            )
            SELECT report_account_id AS gl_account_id, source_gl_code AS gl_code,
                   source_name AS account_name, classifier_code, classifier_name,
                   trial_balance_group, trial_balance_order, income_statement_order,
                   account_order, balance_nature,
                   CASE WHEN :reportType = 'income-statement' THEN 0.00
                        WHEN balance_nature = 'D' THEN opening_debit - opening_credit
                        ELSE opening_credit - opening_debit END AS opening_balance,
                   period_debit AS debits, period_credit AS credits,
                   CASE WHEN :reportType = 'income-statement' AND balance_nature = 'D' THEN period_debit - period_credit
                        WHEN :reportType = 'income-statement' THEN period_credit - period_debit
                        WHEN balance_nature = 'D' THEN closing_debit - closing_credit
                        ELSE closing_credit - closing_debit END AS closing_balance
              FROM report_amounts
             ORDER BY CASE WHEN :reportType = 'income-statement' AND classifier_code = '005' THEN 1
                           WHEN :reportType = 'income-statement' AND classifier_code = '004' THEN 2
                           ELSE COALESCE(trial_balance_order, income_statement_order, 32767) END,
                      COALESCE(account_order, 9223372036854775807), source_gl_code
            """;

    private static final String CONTROL_SQL = """
            WITH scoped AS (
                SELECT account.classification_enum,
                       CASE WHEN journal_entry.type_enum = 2 THEN journal_entry.amount ELSE 0.00 END AS debit,
                       CASE WHEN journal_entry.type_enum = 1 THEN journal_entry.amount ELSE 0.00 END AS credit
                  FROM acc_gl_journal_entry journal_entry
                  JOIN acc_gl_account account ON account.id = journal_entry.account_id
                 WHERE journal_entry.entry_date BETWEEN :fromDate AND :toDate
                   AND (:officeExternalId IS NULL OR journal_entry.dimensions ->> 'office' = :officeExternalId)
                   AND (NOT :excludeAnnualClosing OR account.classification_enum NOT IN (4, 5) OR NOT EXISTS (
                        SELECT 1 FROM credesal_arissto_gl_journal provenance
                         WHERE provenance.target_transaction_id = journal_entry.transaction_id
                           AND provenance.source_journal_type = '003'
                           AND provenance.source_journal_date BETWEEN :financialYearStart AND :toDate))
            )
            SELECT COALESCE(SUM(debit), 0.00) AS debits,
                   COALESCE(SUM(credit), 0.00) AS credits,
                   COALESCE(SUM(debit), 0.00) - COALESCE(SUM(credit), 0.00) AS trial_balance_variance,
                   COALESCE(SUM(CASE WHEN classification_enum = 1 THEN debit - credit ELSE 0.00 END), 0.00) AS assets,
                   COALESCE(SUM(CASE WHEN classification_enum = 2 THEN credit - debit ELSE 0.00 END), 0.00) AS liabilities,
                   COALESCE(SUM(CASE WHEN classification_enum = 3 THEN credit - debit ELSE 0.00 END), 0.00) AS equity,
                   COALESCE(SUM(CASE WHEN classification_enum = 4 THEN credit - debit ELSE 0.00 END), 0.00) AS income,
                   COALESCE(SUM(CASE WHEN classification_enum = 5 THEN debit - credit ELSE 0.00 END), 0.00) AS expense
              FROM scoped
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;
    private final PlatformSecurityContext securityContext;

    @Override
    public CredesalFinancialReportData run(String reportType, LocalDate fromDate, LocalDate toDate, String officeExternalId,
            String closingMode, boolean includeZero) {
        securityContext.authenticatedUser().validateHasPermissionTo(PERMISSION);
        validateRequest(reportType, fromDate, toDate, closingMode);
        LocalDate effectiveFrom = reportType.equals("balance-sheet") ? LEDGER_ORIGIN : fromDate;
        String effectiveClosingMode = reportType.equals("income-statement") ? "pre-closing"
                : reportType.equals("trial-balance") ? closingMode : "post-closing";
        boolean excludeAnnualClosing = reportType.equals("income-statement")
                || reportType.equals("trial-balance") && effectiveClosingMode.equals("pre-closing");
        MapSqlParameterSource parameters = new MapSqlParameterSource().addValue("reportType", reportType)
                .addValue("fromDate", effectiveFrom).addValue("toDate", toDate)
                .addValue("financialYearStart", LocalDate.of(toDate.getYear(), 1, 1))
                .addValue("officeExternalId", officeExternalId, Types.VARCHAR).addValue("excludeAnnualClosing", excludeAnnualClosing);
        validateOffice(officeExternalId);
        validateDimensions(parameters);
        Map<String, Object> metadata = jdbcTemplate.queryForMap(PRESENTATION_METADATA_SQL, Map.of());
        if (((Number) metadata.get("version_count")).intValue() != 1 || ((Number) metadata.get("hash_count")).intValue() != 1) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.presentation.drift",
                    "Credesal report presentation metadata is missing or drifted");
        }
        List<Map<String, Object>> rows = reportType.equals("general-ledger") ? jdbcTemplate.queryForList(GENERAL_LEDGER_SQL, parameters)
                : jdbcTemplate.queryForList(PRESENTED_REPORT_SQL, parameters);
        if (!includeZero && !reportType.equals("general-ledger")) {
            rows = rows.stream().filter(this::hasNonZeroMeasure).toList();
        }
        Map<String, Object> controls = new LinkedHashMap<>(jdbcTemplate.queryForMap(CONTROL_SQL, parameters));
        BigDecimal currentResult = decimal(controls.get("income")).subtract(decimal(controls.get("expense")));
        controls.put("current_result", currentResult);
        controls.put("balance_sheet_variance", decimal(controls.get("assets")).subtract(decimal(controls.get("liabilities")))
                .subtract(decimal(controls.get("equity"))).subtract(currentResult));
        controls.put("dimension_scope", officeExternalId == null ? "consolidated" : "agency");
        return new CredesalFinancialReportData(reportType, effectiveFrom, toDate, officeExternalId, effectiveClosingMode,
                String.valueOf(metadata.get("presentation_version")), String.valueOf(metadata.get("source_snapshot_sha256")), rows,
                controls);
    }

    private void validateRequest(String reportType, LocalDate fromDate, LocalDate toDate, String closingMode) {
        if (!REPORT_TYPES.contains(reportType)) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.type.invalid", "Unsupported report type");
        }
        if (!Set.of("pre-closing", "post-closing").contains(closingMode)) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.closing.mode.invalid", "Unsupported closing mode");
        }
        if (!reportType.equals("balance-sheet") && fromDate == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.from.date.required", "fromDate is required");
        }
        if (fromDate != null && fromDate.isAfter(toDate)) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.date.range.invalid", "fromDate must not exceed toDate");
        }
    }

    private void validateOffice(String officeExternalId) {
        if (officeExternalId != null) {
            Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM m_office WHERE external_id = :officeExternalId",
                    Map.of("officeExternalId", officeExternalId), Integer.class);
            if (count == null || count != 1) {
                throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.office.invalid",
                        "officeExternalId must identify exactly one office");
            }
        }
    }

    private void validateDimensions(MapSqlParameterSource parameters) {
        Integer mismatches = jdbcTemplate.queryForObject(DIMENSION_INTEGRITY_SQL, parameters, Integer.class);
        if (mismatches != null && mismatches > 0) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.office.dimension.mismatch",
                    "Journal office dimensions do not agree with native office external IDs", mismatches);
        }
    }

    private boolean hasNonZeroMeasure(Map<String, Object> row) {
        return decimal(row.get("opening_balance")).signum() != 0 || decimal(row.get("debits")).signum() != 0
                || decimal(row.get("credits")).signum() != 0 || decimal(row.get("closing_balance")).signum() != 0;
    }

    private BigDecimal decimal(Object value) {
        return value == null ? BigDecimal.ZERO : (BigDecimal) value;
    }
}
