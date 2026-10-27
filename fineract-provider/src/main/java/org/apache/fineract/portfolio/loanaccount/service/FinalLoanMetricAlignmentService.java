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
package org.apache.fineract.portfolio.loanaccount.service;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingCutoffMigrationValidationService;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.charge.domain.Charge;
import org.apache.fineract.portfolio.charge.domain.ChargeRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.FinalLoanMetrics;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class FinalLoanMetricAlignmentService {

    private final LoanRepositoryWrapper loans;
    private final ChargeRepositoryWrapper charges;
    private final AccountingOperationalMigrationService migration;
    private final AccountingCutoffMigrationValidationService cutoff;
    private final PlatformSecurityContext security;
    private final JdbcTemplate jdbc;
    private static final Gson JSON = new Gson();

    @Transactional
    public Map<String, Object> read(long loanId, String cutoffDate, long insuranceChargeId, long recurringInsuranceChargeId) {
        return migration.execute(() -> {
            LocalDate firstDay = LocalDate.parse(cutoffDate);
            cutoff.requireExactActiveCutoff(firstDay);
            Loan loan = loans.findOneWithNotFoundDetection(loanId, true);
            verifyLoan(loan, loan.getExternalId().getValue());
            var baseline = FinalLoanMetrics.baseline(loan);
            return Map.of("loanId", loanId, "cutoffDate", cutoffDate, "continuationReady",
                    baseline != null && baseline.getMigrationInterestForecast() != null, "alignmentVersion",
                    jdbc.queryForObject("SELECT COALESCE(MAX(id),0) FROM credesal_loan_metric_alignment WHERE loan_id=?", Long.class,
                            loanId),
                    "metrics", FinalLoanMetrics.read(loan, firstDay.minusDays(1), Set.of(insuranceChargeId, recurringInsuranceChargeId)));
        });
    }

    @Transactional
    public Map<String, Object> align(long loanId, String body) {
        try {
            return migration.execute(() -> execute(loanId, JsonParser.parseString(body).getAsJsonObject()));
        } catch (IllegalArgumentException | java.time.DateTimeException exception) {
            throw invalid(exception.getMessage());
        }
    }

    private Map<String, Object> execute(long loanId, JsonObject request) {
        Set<String> allowed = Set.of("sourceSystem", "sourceLoanExternalId", "cutoffDate", "requestId", "sourceObservedAt",
                "insuranceChargeId", "recurringInsuranceChargeId", "penaltyChargeId", "expected", "targets");
        if (!request.keySet().equals(allowed)) {
            throw invalid("All final metric request fields are required; unknown fields are rejected");
        }
        if (!"ARISSTO".equals(text(request, "sourceSystem"))) {
            throw invalid("Final alignment requires Arissto source ownership");
        }
        LocalDate firstDay = LocalDate.parse(text(request, "cutoffDate"));
        cutoff.requireExactActiveCutoff(firstDay);
        String requestId = text(request, "requestId");
        String observedAt = text(request, "sourceObservedAt");
        if (requestId.length() > 160 || observedAt.length() > 100) {
            throw invalid("Invalid request identity/observation");
        }
        java.time.OffsetDateTime.parse(observedAt);
        jdbc.queryForObject("SELECT id FROM m_loan WHERE id=? FOR UPDATE", Long.class, loanId);
        Loan loan = loans.findOneWithNotFoundDetection(loanId, true);
        verifyLoan(loan, text(request, "sourceLoanExternalId"));
        if (jdbc.queryForObject(
                "SELECT COUNT(*) FROM m_loan_transaction WHERE loan_id=? AND is_reversed=false AND transaction_date>=? AND transaction_type_enum IN (1,2)",
                Long.class, loanId, firstDay) > 0) {
            throw invalid("Native disbursement/repayment activity exists on or after Fineract starts");
        }
        long insuranceId = request.get("insuranceChargeId").getAsLong();
        long recurringId = request.get("recurringInsuranceChargeId").getAsLong();
        long penaltyId = request.get("penaltyChargeId").getAsLong();
        Set<Long> insuranceIds = Set.of(insuranceId, recurringId);
        Charge insuranceDefinition = charges.findOneWithNotFoundDetection(insuranceId);
        Charge penaltyDefinition = charges.findOneWithNotFoundDetection(penaltyId);
        validateCharge(insuranceDefinition, loan, false);
        validateCharge(penaltyDefinition, loan, true);
        Charge recurring = charges.findOneWithNotFoundDetection(recurringId);
        if (!recurring.isActive() || !recurring.isLoanCharge() || recurring.isPenalty()
                || !loan.getCurrency().getCode().equals(recurring.getCurrencyCode()) || recurring.getChargeCalculation() != 8
                || recurring.getChargeTimeType() != 8) {
            throw invalid("Invalid recurring insurance definition");
        }
        Map<String, BigDecimal> targets = amounts(request.getAsJsonObject("targets"));
        Map<String, BigDecimal> expected = amounts(request.getAsJsonObject("expected"));
        LocalDate sourceDay = firstDay.minusDays(1);
        Map<String, BigDecimal> before = FinalLoanMetrics.read(loan, sourceDay, insuranceIds);
        String hash = digest(JSON.toJson(new TreeMap<>(Map.of("loanId", loanId, "source", text(request, "sourceLoanExternalId"),
                "cutoffDate", firstDay.toString(), "sourceObservedAt", observedAt, "targets", new TreeMap<>(targets), "expected",
                new TreeMap<>(expected), "insurance", insuranceId, "recurring", recurringId, "penalty", penaltyId))));
        List<Map<String, Object>> prior = jdbc.queryForList(
                "SELECT payload_hash FROM credesal_loan_metric_alignment WHERE loan_id=? AND request_id=?", loanId, requestId);
        if (!prior.isEmpty()) {
            if (!hash.equals(prior.getFirst().get("payload_hash")) || !before.equals(targets)) {
                throw invalid("Final request identity reused with changed payload or drifted state");
            }
            return Map.of("loanId", loanId, "metrics", before, "alreadyApplied", true);
        }
        if (!before.equals(expected)) {
            throw invalid("Final metric state changed after comparison");
        }
        if (loan.getStatus().getValue() != 300 && targets.values().stream().anyMatch(v -> v.signum() != 0)
                && (targets.get("outstandingPrincipal").signum() > 0 || targets.get("accruedInterest").signum() > 0
                        || targets.get("mora").signum() > 0 || targets.get("insuranceOutstanding").signum() > 0)) {
            throw invalid("A non-active loan cannot acquire a collectible opening obligation");
        }
        var journals = journals(loanId);
        boolean changed = !before.equals(targets);
        var baseline = FinalLoanMetrics.baseline(loan);
        if (changed || baseline == null || baseline.getMigrationInterestForecast() == null) {
            FinalLoanMetrics.apply(loan, sourceDay, targets, insuranceIds, insuranceDefinition, penaltyDefinition);
            loans.saveAndFlush(loan);
            // Refresh the normal loan-detail overdue projection at the same source boundary.
            var currency = loan.getCurrency();
            BigDecimal principalDue = BigDecimal.ZERO, interestDue = BigDecimal.ZERO, feeDue = BigDecimal.ZERO,
                    penaltyDue = BigDecimal.ZERO;
            LocalDate earliestDue = sourceDay;
            for (var row : loan.getRepaymentScheduleInstallments()) {
                if (!row.getDueDate().isAfter(sourceDay)) {
                    principalDue = principalDue.add(row.getPrincipalOutstanding(currency).getAmount());
                    interestDue = interestDue.add(row.getInterestOutstanding(currency).getAmount());
                    feeDue = feeDue.add(row.getFeeChargesOutstanding(currency).getAmount());
                    penaltyDue = penaltyDue.add(row.getPenaltyChargesOutstanding(currency).getAmount());
                    if (row.getTotalOutstanding(currency).isGreaterThanZero() && row.getDueDate().isBefore(earliestDue)) {
                        earliestDue = row.getDueDate();
                    }
                }
            }
            BigDecimal totalDue = principalDue.add(interestDue).add(feeDue).add(penaltyDue);
            int updated = jdbc.update(
                    "UPDATE m_loan_arrears_aging SET principal_overdue_derived=?,interest_overdue_derived=?,fee_charges_overdue_derived=?,penalty_charges_overdue_derived=?,total_overdue_derived=?,overdue_since_date_derived=? WHERE loan_id=?",
                    principalDue, interestDue, feeDue, penaltyDue, totalDue, totalDue.signum() == 0 ? null : earliestDue, loanId);
            if (updated == 0) {
                jdbc.update(
                        "INSERT INTO m_loan_arrears_aging(loan_id,principal_overdue_derived,interest_overdue_derived,fee_charges_overdue_derived,penalty_charges_overdue_derived,total_overdue_derived,overdue_since_date_derived) VALUES(?,?,?,?,?,?,?)",
                        loanId, principalDue, interestDue, feeDue, penaltyDue, totalDue, totalDue.signum() == 0 ? null : earliestDue);
            }
        }
        Map<String, BigDecimal> after = FinalLoanMetrics.read(loan, sourceDay, insuranceIds);
        if (!after.equals(targets) || !journals.equals(journals(loanId))) {
            throw invalid("Final metrics or GL invariants failed");
        }
        jdbc.update(
                "INSERT INTO credesal_loan_metric_alignment(loan_id,request_id,payload_hash,source_through_date,source_observed_at,before_json,target_json,after_json,actor_id,changed,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                loanId, requestId, hash, sourceDay, observedAt, JSON.toJson(before), JSON.toJson(targets), JSON.toJson(after),
                security.authenticatedUser().getId(), changed);
        return Map.of("loanId", loanId, "metrics", after, "changed", changed, "alreadyApplied", false);
    }

    private List<Map<String, Object>> journals(long loanId) {
        return jdbc.queryForList(
                "SELECT j.* FROM acc_gl_journal_entry j WHERE j.loan_transaction_id IN (SELECT id FROM m_loan_transaction WHERE loan_id=?) ORDER BY j.id",
                loanId);
    }

    private static void verifyLoan(Loan loan, String external) {
        if (external == null || !external.equals(loan.getExternalId().getValue())
                || !external.matches("(?:PROOF:[A-Za-z0-9:_-]+:)?ARISSTO:CRD:[0-9]+")) {
            throw invalid("Final alignment requires the exact imported Arissto loan identity");
        }
        if (!Set.of(200, 300, 600, 601, 602, 700).contains(loan.getStatus().getValue())) {
            throw invalid("Unsupported loan lifecycle state");
        }
    }

    private static void validateCharge(Charge charge, Loan loan, boolean penalty) {
        if (!charge.isActive() || !charge.isLoanCharge() || charge.isPenalty() != penalty
                || !loan.getCurrency().getCode().equals(charge.getCurrencyCode()) || charge.getChargeCalculation() != 1
                || charge.getChargeTimeType() != 2) {
            throw invalid("Final baseline requires a matching flat specified-date charge definition");
        }
    }

    private static Map<String, BigDecimal> amounts(JsonObject object) {
        if (object == null) {
            throw invalid("Expected and target vectors are required");
        }
        Map<String, BigDecimal> result = new LinkedHashMap<>();
        object.entrySet().forEach(e -> result.put(e.getKey(), e.getValue().getAsBigDecimal()));
        FinalLoanMetrics.validate(result);
        return FinalLoanMetrics.normalize(result);
    }

    private static String text(JsonObject object, String field) {
        if (!object.has(field) || !object.get(field).isJsonPrimitive() || !object.get(field).getAsJsonPrimitive().isString()) {
            throw invalid("Missing or invalid " + field);
        }
        String value = object.get(field).getAsString();
        if (value == null || value.isBlank()) {
            throw invalid("Missing " + field);
        }
        return value;
    }

    private static String digest(String input) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static GeneralPlatformDomainRuleException invalid(String message) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.final.metrics.invalid", message);
    }
}
