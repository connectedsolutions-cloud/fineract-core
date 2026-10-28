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
package org.apache.fineract.portfolio.loanaccount.domain;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.portfolio.charge.domain.Charge;

/** End-of-import operational corrections. Never creates or changes loan transactions or journals. */
public final class FinalLoanMetrics {

    public static final List<String> KEYS = List.of("paidPrincipal", "outstandingPrincipal", "paidInterest", "accruedInterest",
            "duePrincipal", "mora", "insurancePaid", "insuranceOutstanding");
    private static final BigDecimal ZERO = new BigDecimal("0.00");

    private FinalLoanMetrics() {}

    public static LoanRepaymentScheduleInstallment baseline(Loan loan) {
        return loan.getRepaymentScheduleInstallments().stream().filter(LoanRepaymentScheduleInstallment::isMigrationMetricBaseline)
                .findFirst().orElse(null);
    }

    public static LocalDate sourceDay(List<LoanRepaymentScheduleInstallment> rows) {
        return rows.stream().filter(LoanRepaymentScheduleInstallment::isMigrationMetricBaseline)
                .map(LoanRepaymentScheduleInstallment::getDueDate).max(LocalDate::compareTo).orElse(null);
    }

    /** Refresh persisted native projections without replaying imported cash history. */
    public static void refresh(Loan loan) {
        var anchor = baseline(loan);
        if (anchor == null) throw new IllegalStateException("A migration baseline is required");
        projectCharges(loan, anchor);
        loan.getSummary().updateSummary(loan.getCurrency(), loan.getLoanRepaymentScheduleDetail().getPrincipal(),
                loan.getRepaymentScheduleInstallments(), loan.getLoanCharges(),
                Money.of(loan.getCurrency(), loan.getSummary().getTotalCapitalizedIncome()),
                Money.of(loan.getCurrency(), loan.getSummary().getTotalCapitalizedIncomeAdjustment()));
    }

    public static void ensureChargePeriod(Loan loan, LocalDate day) {
        if (loan.getRepaymentScheduleInstallments().stream().anyMatch(r -> !r.getDueDate().isBefore(day))) return;
        var rows = loan.getRepaymentScheduleInstallments();
        LocalDate from = rows.stream().map(LoanRepaymentScheduleInstallment::getDueDate).max(LocalDate::compareTo).orElseThrow();
        int number = rows.stream().mapToInt(LoanRepaymentScheduleInstallment::getInstallmentNumber).max().orElse(0) + 1;
        var row = new LoanRepaymentScheduleInstallment(loan, number, from, day, ZERO, ZERO, ZERO, ZERO, false, null, null);
        row.setAdditional(true);
        loan.addLoanRepaymentScheduleInstallment(row);
    }

    public static BigDecimal money(BigDecimal value) {
        return value == null ? ZERO : value.setScale(2, RoundingMode.HALF_EVEN);
    }

    public static void validateObservation(Map<String, BigDecimal> values) {
        if (!values.keySet().equals(Set.copyOf(KEYS))) {
            throw new IllegalArgumentException("Exactly eight metric amounts are required");
        }
        for (BigDecimal value : values.values()) {
            if (value == null || value.stripTrailingZeros().scale() > 2) {
                throw new IllegalArgumentException("Metrics must be currency amounts with at most two decimal places");
            }
        }
    }

    public static void validate(Map<String, BigDecimal> values) {
        validateObservation(values);
        if (values.values().stream().anyMatch(value -> value.signum() < 0)) {
            throw new IllegalArgumentException("Target metrics must be nonnegative");
        }
        if (values.get("duePrincipal").compareTo(values.get("outstandingPrincipal")) > 0) {
            throw new IllegalArgumentException("Due principal cannot exceed outstanding principal");
        }
    }

    public static boolean insurance(LoanCharge charge, Set<Long> insuranceIds) {
        return charge.isActive() && !charge.isPenaltyCharge() && insuranceIds.contains(charge.getCharge().getId());
    }

    public static Map<String, BigDecimal> read(Loan loan, LocalDate sourceDay, Set<Long> insuranceIds) {
        var c = loan.getCurrency();
        var s = loan.getSummary();
        Map<String, BigDecimal> result = new LinkedHashMap<>();
        result.put("paidPrincipal", money(s.getTotalPrincipalRepaid()));
        result.put("outstandingPrincipal", money(s.getTotalPrincipalOutstanding()));
        result.put("paidInterest", money(s.getTotalInterestRepaid()));
        BigDecimal due = ZERO, interest = ZERO;
        LocalDate firstDay = sourceDay.plusDays(1);
        for (var row : loan.getRepaymentScheduleInstallments()) {
            if (!row.getDueDate().isAfter(sourceDay)) {
                due = due.add(row.getPrincipalOutstanding(c).getAmount());
            }
            if (!row.getDueDate().isAfter(firstDay)) {
                interest = interest.add(row.getInterestOutstanding(c).getAmount());
            } else if (row.getFromDate() != null && !row.getFromDate().isAfter(firstDay)) {
                long days = ChronoUnit.DAYS.between(row.getFromDate(), row.getDueDate());
                if (days > 0) {
                    BigDecimal accrued = row.getInterestCharged(c).getAmount()
                            .multiply(BigDecimal.valueOf(ChronoUnit.DAYS.between(row.getFromDate(), firstDay)))
                            .divide(BigDecimal.valueOf(days), 12, RoundingMode.HALF_EVEN).subtract(row.getInterestPaid(c).getAmount())
                            .subtract(row.getInterestWaived(c).getAmount());
                    interest = interest.add(money(accrued.max(BigDecimal.ZERO)));
                }
            }
        }
        result.put("accruedInterest", money(interest));
        result.put("duePrincipal", money(due));
        BigDecimal mora = ZERO, paid = ZERO, outstanding = ZERO;
        for (var charge : loan.getActiveCharges()) {
            if (insurance(charge, insuranceIds)) {
                paid = paid.add(money(charge.getAmountPaid()));
                outstanding = outstanding.add(dueOutstanding(charge, sourceDay));
            }
            if (charge.isPenaltyCharge()) {
                mora = mora.add(dueOutstanding(charge, sourceDay));
            }
        }
        result.put("mora", money(mora));
        result.put("insurancePaid", money(paid));
        result.put("insuranceOutstanding", money(outstanding));
        return result;
    }

    private static BigDecimal dueOutstanding(LoanCharge charge, LocalDate sourceDay) {
        if (charge.isInstalmentFee()) {
            return charge.getLoanInstallmentCharge().stream().filter(i -> !i.getInstallment().getDueDate().isAfter(sourceDay))
                    .map(i -> money(i.getAmountOutstanding())).reduce(ZERO, BigDecimal::add);
        }
        return charge.getDueLocalDate() != null && !charge.getDueLocalDate().isAfter(sourceDay) ? money(charge.amountOutstanding()) : ZERO;
    }

    public static void apply(Loan loan, LocalDate sourceDay, Map<String, BigDecimal> targets, Set<Long> insuranceIds,
            Charge insuranceDefinition, Charge penaltyDefinition) {
        validate(targets);
        var currency = loan.getCurrency();
        var capitalized = Money.of(currency, loan.getSummary().getTotalCapitalizedIncome());
        var capitalizedAdjustment = Money.of(currency, loan.getSummary().getTotalCapitalizedIncomeAdjustment());
        List<LoanRepaymentScheduleInstallment> original = new ArrayList<>(loan.getRepaymentScheduleInstallments());
        if (original.isEmpty()) {
            throw new IllegalArgumentException("Cannot align an originated loan without its native schedule");
        }
        int max = original.stream().mapToInt(LoanRepaymentScheduleInstallment::getInstallmentNumber).max().orElse(0);
        // A separate, explicitly additional opening row carries migration settlement corrections.
        var opening = loan.getRepaymentScheduleInstallments().stream().filter(r -> r.isMigrationMetricBaseline()).findFirst().orElse(null);
        if (opening == null) {
            opening = new LoanRepaymentScheduleInstallment(loan, max + 1, sourceDay.minusDays(1), sourceDay, BigDecimal.ZERO,
                    BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, false, null, null);
            opening.setAdditional(true);
            opening.setMigrationMetricBaseline(true);
            loan.addLoanRepaymentScheduleInstallment(opening);
        }
        final var anchor = opening;
        List<LoanRepaymentScheduleInstallment> rows = new ArrayList<>(loan.getRepaymentScheduleInstallments());
        List<LoanRepaymentScheduleInstallment> future = rows.stream().filter(r -> r != anchor && r.getDueDate().isAfter(sourceDay))
                .toList();
        BigDecimal notDue = targets.get("outstandingPrincipal").subtract(targets.get("duePrincipal"));
        if (notDue.signum() > 0 && future.isEmpty()) {
            throw new IllegalArgumentException(
                    "Non-due principal requires a remaining future due date; import the effective source schedule first");
        }
        Map<LoanRepaymentScheduleInstallment, BigDecimal> weights = new LinkedHashMap<>();
        for (var row : future) {
            weights.put(row, row.getPrincipalOutstanding(currency).getAmount().max(BigDecimal.ZERO));
        }
        Map<LoanRepaymentScheduleInstallment, BigDecimal> allocation = distribute(notDue, weights);
        Map<LoanRepaymentScheduleInstallment, BigDecimal> pastWeights = new LinkedHashMap<>();
        for (var row : rows) {
            if (row != anchor && !row.getDueDate().isAfter(sourceDay)) {
                pastWeights.put(row, row.getPrincipalOutstanding(currency).getAmount().max(BigDecimal.ZERO));
            }
        }
        if (pastWeights.isEmpty()) {
            pastWeights.put(anchor, BigDecimal.ONE);
        }
        Map<LoanRepaymentScheduleInstallment, BigDecimal> pastAllocation = distribute(targets.get("duePrincipal"), pastWeights);
        LocalDate firstDay = sourceDay.plusDays(1);
        for (var row : rows) {
            row.setPrincipalCompleted(row == anchor ? targets.get("paidPrincipal") : ZERO);
            BigDecimal outstanding = pastAllocation.getOrDefault(row, ZERO).add(allocation.getOrDefault(row, ZERO));
            row.setPrincipal(money(row.getPrincipalCompleted()).add(money(row.getPrincipalWrittenOff())).add(outstanding));
            row.setCreditedPrincipal(ZERO);
            row.setPostDueInterestCharged(ZERO);
            if (row != anchor) {
                // Preserve the pre-handoff forecast for schedule display, but do not
                // turn that unearned estimate into collectible accrued interest.
                if (row.getDueDate().isAfter(sourceDay) && row.getMigrationInterestForecast() == null)
                    row.setMigrationInterestForecast(money(row.getInterestCharged()));
                row.setInterestCharged(money(row.getInterestWaived()).add(money(row.getInterestWrittenOff())));
                row.setInterestPaid(ZERO);
            }
        }
        BigDecimal writtenOff = rows.stream().map(r -> money(r.getPrincipalWrittenOff())).reduce(ZERO, BigDecimal::add);
        anchor.setCreditedPrincipal(targets.get("paidPrincipal").add(targets.get("outstandingPrincipal")).add(writtenOff)
                .subtract(loan.getLoanRepaymentScheduleDetail().getPrincipal().getAmount()).subtract(capitalized.getAmount()));
        anchor.setMigrationInterestForecast(ZERO);
        anchor.setInterestPaid(targets.get("paidInterest"));
        anchor.setInterestCharged(targets.get("paidInterest").add(targets.get("accruedInterest")));
        alignCharges(loan, sourceDay, insuranceIds, insuranceDefinition, false, targets.get("insurancePaid"),
                targets.get("insuranceOutstanding"));
        alignCharges(loan, sourceDay, insuranceIds, penaltyDefinition, true, null, targets.get("mora"));
        projectCharges(loan, anchor);
        for (var row : rows) {
            row.updateObligationsMet(currency, sourceDay);
        }
        List<LoanRepaymentScheduleInstallment> chronological = rows.stream()
                .sorted(Comparator.comparing(LoanRepaymentScheduleInstallment::getDueDate)
                        .thenComparing(LoanRepaymentScheduleInstallment::getInstallmentNumber))
                .toList();
        for (int i = 0; i < chronological.size(); i++) {
            chronological.get(i).setInstallmentNumber(i + 1);
        }
        loan.getSummary().updateSummary(currency, loan.getLoanRepaymentScheduleDetail().getPrincipal(), rows, loan.getLoanCharges(),
                capitalized, capitalizedAdjustment);
        if (!read(loan, sourceDay, insuranceIds).equals(normalize(targets))) {
            throw new IllegalStateException("Final native metric vector did not match");
        }
    }

    public static Map<String, BigDecimal> normalize(Map<String, BigDecimal> values) {
        Map<String, BigDecimal> result = new LinkedHashMap<>();
        values.forEach((k, v) -> result.put(k, money(v)));
        return result;
    }

    static Map<LoanRepaymentScheduleInstallment, BigDecimal> distribute(BigDecimal total,
            Map<LoanRepaymentScheduleInstallment, BigDecimal> weights) {
        Map<LoanRepaymentScheduleInstallment, BigDecimal> result = new LinkedHashMap<>();
        BigDecimal sum = weights.values().stream().reduce(ZERO, BigDecimal::add);
        BigDecimal remaining = money(total);
        int index = 0;
        for (var entry : weights.entrySet()) {
            BigDecimal amount = ++index == weights.size() ? remaining
                    : sum.signum() == 0 ? ZERO : total.multiply(entry.getValue()).divide(sum, 2, RoundingMode.DOWN).min(remaining);
            result.put(entry.getKey(), amount);
            remaining = remaining.subtract(amount);
        }
        return result;
    }

    private static void alignCharges(Loan loan, LocalDate day, Set<Long> insuranceIds, Charge definition, boolean penalty,
            BigDecimal paidTarget, BigDecimal outstandingTarget) {
        String external = "ARISSTO:CRD-METRICS:" + (penalty ? "MORA:" : "INS:") + loan.getId();
        var baseline = loan.getActiveCharges().stream()
                .filter(c -> c.getExternalId() != null && external.equals(c.getExternalId().getValue())).findFirst().orElse(null);
        if (baseline == null) {
            baseline = new LoanCharge();
            baseline.setLoan(loan);
            baseline.setCharge(definition);
            baseline.setChargeTime(2);
            baseline.setChargeCalculation(1);
            baseline.setChargePaymentMode(0);
            baseline.setSubmittedOnDate(day);
            baseline.setDueDate(day);
            baseline.setPenaltyCharge(penalty);
            baseline.setExternalId(new ExternalId(external));
            baseline.setActive(true);
            baseline.setAmount(ZERO);
            baseline.setAmountOrPercentage(ZERO);
            baseline.setAmountPaid(ZERO);
            baseline.setAmountOutstanding(ZERO);
            loan.addCharge(baseline);
        }
        BigDecimal remainingPaid = paidTarget;
        List<LoanCharge> charges = loan.getActiveCharges().stream()
                .sorted(Comparator.comparing(c -> c.getId() == null ? Long.MAX_VALUE : c.getId())).toList();
        for (var charge : charges) {
            if (charge == baseline || (penalty ? !charge.isPenaltyCharge() : !insurance(charge, insuranceIds))) {
                continue;
            }
            if (charge.isInstalmentFee()) {
                for (var installment : charge.getLoanInstallmentCharge()) {
                    BigDecimal paid = money(installment.getAmountPaid());
                    if (remainingPaid != null) {
                        paid = paid.min(remainingPaid);
                        remainingPaid = remainingPaid.subtract(paid);
                    }
                    BigDecimal out = installment.getInstallment().getDueDate().isAfter(day)
                            ? money(installment.getAmount()).subtract(paid).subtract(money(installment.getAmountWaived()))
                                    .subtract(money(installment.getAmountWrittenOff())).max(ZERO)
                            : ZERO;
                    installment.alignMigrationAmounts(paid, out);
                }
                charge.setAmountPaid(
                        charge.getLoanInstallmentCharge().stream().map(i -> money(i.getAmountPaid())).reduce(ZERO, BigDecimal::add));
                charge.setAmountOutstanding(
                        charge.getLoanInstallmentCharge().stream().map(i -> money(i.getAmountOutstanding())).reduce(ZERO, BigDecimal::add));
            } else {
                BigDecimal paid = money(charge.getAmountPaid());
                if (remainingPaid != null) {
                    paid = paid.min(remainingPaid);
                    remainingPaid = remainingPaid.subtract(paid);
                    charge.setAmountPaid(paid);
                }
                if (charge.getDueLocalDate() != null && !charge.getDueLocalDate().isAfter(day)) {
                    charge.setAmountOutstanding(ZERO);
                }
            }
            charge.setAmount(money(charge.getAmountPaid()).add(money(charge.getAmountOutstanding())).add(money(charge.getAmountWaived()))
                    .add(money(charge.getAmountWrittenOff())));
            if (!charge.getChargeCalculation().isPercentageBased()) {
                charge.setAmountOrPercentage(charge.getAmount());
            }
            charge.setPaid(charge.amountOutstanding().signum() == 0);
        }
        baseline.setAmountPaid(remainingPaid == null ? money(baseline.getAmountPaid()) : remainingPaid);
        baseline.setAmountOutstanding(outstandingTarget);
        baseline.setAmount(baseline.getAmountPaid().add(outstandingTarget));
        baseline.setAmountOrPercentage(baseline.getAmount());
        baseline.setPaid(outstandingTarget.signum() == 0);
    }

    private static void projectCharges(Loan loan, LoanRepaymentScheduleInstallment anchor) {
        List<LoanRepaymentScheduleInstallment> rows = loan.getRepaymentScheduleInstallments().stream()
                .sorted(Comparator.comparing(LoanRepaymentScheduleInstallment::getDueDate)).toList();
        for (var row : rows) {
            row.setFeeChargesCharged(ZERO);
            row.setFeeChargesPaid(ZERO);
            row.setFeeChargesWaived(ZERO);
            row.setFeeChargesWrittenOff(ZERO);
            row.setPenaltyCharges(ZERO);
            row.setPenaltyChargesPaid(ZERO);
            row.setPenaltyChargesWaived(ZERO);
            row.setPenaltyChargesWrittenOff(ZERO);
        }
        for (var charge : loan.getActiveCharges()) {
            if (charge.isDueAtDisbursement()) {
                continue;
            }
            if (charge.isInstalmentFee()) {
                for (var item : charge.getLoanInstallmentCharge()) {
                    project(item.getInstallment(), charge.isPenaltyCharge(), item.getAmount(), item.getAmountPaid(), item.getAmountWaived(),
                            item.getAmountWrittenOff());
                }
            } else {
                var row = charge.getExternalId() != null && charge.getExternalId().getValue().startsWith("ARISSTO:CRD-METRICS:") ? anchor
                        : rows.stream().filter(r -> charge.getDueLocalDate() != null && !r.getDueDate().isBefore(charge.getDueLocalDate()))
                                .findFirst().orElse(rows.getLast());
                project(row, charge.isPenaltyCharge(), charge.getAmount(), charge.getAmountPaid(), charge.getAmountWaived(),
                        charge.getAmountWrittenOff());
            }
        }
    }

    private static void project(LoanRepaymentScheduleInstallment row, boolean penalty, BigDecimal amount, BigDecimal paid,
            BigDecimal waived, BigDecimal writtenOff) {
        if (penalty) {
            row.setPenaltyCharges(money(row.getPenaltyCharges()).add(money(amount)));
            row.setPenaltyChargesPaid(money(row.getPenaltyChargesPaid()).add(money(paid)));
            row.setPenaltyChargesWaived(money(row.getPenaltyChargesWaived()).add(money(waived)));
            row.setPenaltyChargesWrittenOff(money(row.getPenaltyChargesWrittenOff()).add(money(writtenOff)));
        } else {
            row.setFeeChargesCharged(money(row.getFeeChargesCharged()).add(money(amount)));
            row.setFeeChargesPaid(money(row.getFeeChargesPaid()).add(money(paid)));
            row.setFeeChargesWaived(money(row.getFeeChargesWaived()).add(money(waived)));
            row.setFeeChargesWrittenOff(money(row.getFeeChargesWrittenOff()).add(money(writtenOff)));
        }
    }
}
