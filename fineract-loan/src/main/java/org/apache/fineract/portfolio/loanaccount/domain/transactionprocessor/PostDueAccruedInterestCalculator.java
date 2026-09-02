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
package org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor;

import java.math.BigDecimal;
import java.math.MathContext;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.common.domain.DaysInYearType;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;

/** Materializes interest between the last covered schedule date and a late repayment's effective date. */
public class PostDueAccruedInterestCalculator {

    private static final BigDecimal ONE_HUNDRED = BigDecimal.valueOf(100);

    public Money calculateAndApply(final LoanTransaction transaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments) {
        final Money zero = Money.zero(currency);
        if (!transaction.isRepayment() || installments.isEmpty()) {
            return zero;
        }

        final Loan loan = transaction.getLoan() != null ? transaction.getLoan() : installments.getFirst().getLoan();
        if (loan == null) {
            return zero;
        }
        final LoanProductRelatedDetail terms = loan.getLoanProductRelatedDetail();
        final BigDecimal annualRate = terms.getAnnualNominalInterestRate();
        if (annualRate == null || annualRate.signum() <= 0 || !terms.getInterestMethod().isDecliningBalance()
                || terms.getInterestCalculationPeriodMethod() != InterestCalculationPeriodMethod.DAILY) {
            return zero;
        }

        final LocalDate transactionDate = transaction.getTransactionDate();
        final LocalDate latestCoveredDate = installments.stream().filter(installment -> !installment.isAdditional())
                .map(LoanRepaymentScheduleInstallment::getDueDate).filter(dueDate -> !dueDate.isAfter(transactionDate))
                .max(Comparator.naturalOrder()).orElse(null);
        if (latestCoveredDate == null) {
            return zero;
        }

        final List<LoanTransaction> loanTransactions = loan.getLoanTransactions() == null ? List.of() : loan.getLoanTransactions();
        final LocalDate accrualStartDate = loanTransactions.stream().filter(LoanTransaction::isRepayment)
                .map(LoanTransaction::getTransactionDate).filter(date -> date.isAfter(latestCoveredDate) && date.isBefore(transactionDate))
                .max(Comparator.naturalOrder()).orElse(latestCoveredDate);
        if (!accrualStartDate.isBefore(transactionDate)) {
            return zero;
        }

        final Money outstandingPrincipal = installments.stream().map(installment -> installment.getPrincipalOutstanding(currency))
                .reduce(zero, Money::add);
        if (!outstandingPrincipal.isGreaterThanZero()) {
            return zero;
        }

        final MathContext mc = MoneyHelper.getMathContext();
        final BigDecimal yearFraction = yearFraction(accrualStartDate, transactionDate, terms.fetchDaysInYearType(), mc);
        final Money accruedInterest = Money.of(currency,
                outstandingPrincipal.getAmount().multiply(annualRate, mc).divide(ONE_HUNDRED, mc).multiply(yearFraction, mc), mc);
        if (!accruedInterest.isGreaterThanZero()) {
            return zero;
        }

        installments.stream().filter(LoanRepaymentScheduleInstallment::isNotFullyPaidOff)
                .min(Comparator.comparing(LoanRepaymentScheduleInstallment::getDueDate)).orElse(installments.getFirst())
                .addPostDueInterest(transactionDate, accruedInterest);
        return accruedInterest;
    }

    /**
     * Calculates cumulative post-due interest through an accounting date. Unlike {@link #calculateAndApply}, which
     * calculates only the segment needed by the repayment currently being processed, this method reconstructs each
     * outstanding-principal segment after the latest covered schedule date. Periodic accrual can therefore subtract
     * previously posted accrual transactions without reverting to the schedule's assumed principal balance.
     */
    public Money calculateAccruableThrough(final Loan loan, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments, final LocalDate effectiveDate) {
        final Money zero = Money.zero(currency);
        if (loan == null || installments.isEmpty()) {
            return zero;
        }

        final LoanProductRelatedDetail terms = loan.getLoanProductRelatedDetail();
        final BigDecimal annualRate = terms.getAnnualNominalInterestRate();
        if (annualRate == null || annualRate.signum() <= 0 || !terms.getInterestMethod().isDecliningBalance()
                || terms.getInterestCalculationPeriodMethod() != InterestCalculationPeriodMethod.DAILY) {
            return zero;
        }

        final LocalDate latestCoveredDate = installments.stream().filter(installment -> !installment.isAdditional())
                .map(LoanRepaymentScheduleInstallment::getDueDate).filter(dueDate -> !dueDate.isAfter(effectiveDate))
                .max(Comparator.naturalOrder()).orElse(null);
        if (latestCoveredDate == null || !latestCoveredDate.isBefore(effectiveDate)) {
            return zero;
        }

        final List<LoanTransaction> repayments = (loan.getLoanTransactions() == null ? List.<LoanTransaction>of()
                : loan.getLoanTransactions()).stream().filter(transaction -> transaction.isRepayment() && !transaction.isReversed())
                .filter(transaction -> transaction.getTransactionDate().isAfter(latestCoveredDate))
                .sorted(Comparator.comparing(LoanTransaction::getTransactionDate)).toList();

        Money outstandingPrincipal = installments.stream().map(installment -> installment.getPrincipalOutstanding(currency)).reduce(zero,
                Money::add);
        for (LoanTransaction repayment : repayments) {
            outstandingPrincipal = outstandingPrincipal.plus(repayment.getPrincipalPortion(currency));
        }

        final MathContext mc = MoneyHelper.getMathContext();
        BigDecimal accrued = BigDecimal.ZERO;
        LocalDate segmentStart = latestCoveredDate;
        for (LoanTransaction repayment : repayments) {
            if (repayment.getTransactionDate().isAfter(effectiveDate)) {
                break;
            }
            accrued = accrued.add(calculateSegment(outstandingPrincipal, annualRate, segmentStart, repayment.getTransactionDate(),
                    terms.fetchDaysInYearType(), mc), mc);
            outstandingPrincipal = outstandingPrincipal.minus(repayment.getPrincipalPortion(currency));
            segmentStart = repayment.getTransactionDate();
        }
        accrued = accrued
                .add(calculateSegment(outstandingPrincipal, annualRate, segmentStart, effectiveDate, terms.fetchDaysInYearType(), mc), mc);
        return Money.of(currency, accrued, mc);
    }

    private BigDecimal calculateSegment(final Money outstandingPrincipal, final BigDecimal annualRate, final LocalDate startDate,
            final LocalDate endDate, final DaysInYearType daysInYearType, final MathContext mc) {
        if (!outstandingPrincipal.isGreaterThanZero() || !startDate.isBefore(endDate)) {
            return BigDecimal.ZERO;
        }
        return outstandingPrincipal.getAmount().multiply(annualRate, mc).divide(ONE_HUNDRED, mc)
                .multiply(yearFraction(startDate, endDate, daysInYearType, mc), mc);
    }

    private BigDecimal yearFraction(final LocalDate startDate, final LocalDate endDate, final DaysInYearType daysInYearType,
            final MathContext mc) {
        if (!daysInYearType.isActual()) {
            return BigDecimal.valueOf(ChronoUnit.DAYS.between(startDate, endDate)).divide(BigDecimal.valueOf(daysInYearType.getValue()),
                    mc);
        }

        BigDecimal result = BigDecimal.ZERO;
        LocalDate segmentStart = startDate;
        while (segmentStart.isBefore(endDate)) {
            final LocalDate segmentEnd = endDate.isBefore(LocalDate.of(segmentStart.getYear() + 1, 1, 1)) ? endDate
                    : LocalDate.of(segmentStart.getYear() + 1, 1, 1);
            result = result.add(BigDecimal.valueOf(ChronoUnit.DAYS.between(segmentStart, segmentEnd))
                    .divide(BigDecimal.valueOf(segmentStart.lengthOfYear()), mc), mc);
            segmentStart = segmentEnd;
        }
        return result;
    }
}
