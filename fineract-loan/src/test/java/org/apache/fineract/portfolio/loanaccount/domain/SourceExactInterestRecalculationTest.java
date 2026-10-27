/*
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
package org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.SourceExactRepaymentAllocation;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

class SourceExactInterestRecalculationTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static final LocalDate DISBURSED = LocalDate.of(2024, 9, 19);
    private static final LocalDate PAYMENT = LocalDate.of(2024, 9, 24);
    private static final LocalDate FIRST_DUE = LocalDate.of(2024, 10, 20);
    private MockedStatic<MoneyHelper> moneyHelper;
    private CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor processor;
    private Loan loan;
    private LoanRepaymentScheduleInstallment contractual;
    private LoanTransaction transaction;

    @BeforeEach
    void setUp() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, PAYMENT)));
        processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), new PostDueAccruedInterestCalculator());
        loan = mock(Loan.class);
        when(loan.getDisbursementDate()).thenReturn(DISBURSED);
        final LoanProductRelatedDetail terms = mock(LoanProductRelatedDetail.class);
        when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
        when(terms.getAnnualNominalInterestRate()).thenReturn(BigDecimal.ZERO);
        contractual = installment(FIRST_DUE, "130.82");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(contractual));
        transaction = payment(PAYMENT, "0.00", "1.10", "0.00", "0.00");
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
        moneyHelper.close();
    }

    @Test
    void emptyPrefixDefersInterestWithoutMutatingContractualScheduleOrCreatingEarlyPrincipal() {
        assertMoney("0.00", recalculate());
        assertMoney("0.00", transaction.getInterestPortion(CURRENCY));
        assertMoney("1.10", transaction.getSourceExactInterestPortion(CURRENCY));
        assertMoney("0.00", contractual.getInterestPaid(CURRENCY));
        assertMoney("130.82", contractual.getInterestCharged(CURRENCY));
        assertEquals(0, transaction.getLoanTransactionToRepaymentScheduleMappings().size());
    }

    @Test
    void historicalPrefixDoesNotResetPaymentsAlreadyRecordedOnTheContractualLoan() {
        contractual.payInterestComponent(FIRST_DUE, Money.of(CURRENCY, new BigDecimal("130.82")));
        assertMoney("0.00", recalculate());
        assertMoney("130.82", contractual.getInterestPaid(CURRENCY));
        assertMoney("0.00", contractual.getInterestOutstanding(CURRENCY));
    }

    @Test
    void emptyPrefixReturnsOnlyDeclaredPrincipalForNativeEarlyPaymentReduction() {
        transaction = payment(PAYMENT, "5.00", "1.10", "0.00", "0.00");
        assertMoney("5.00", recalculate());
        assertMoney("0.00", transaction.getPrincipalPortion(CURRENCY));
        assertMoney("1.10", transaction.getSourceExactInterestPortion(CURRENCY));
    }

    @Test
    void finalPostingMapsTheEntireFrozenInterestAfterThePrefixCalculation() {
        recalculate();
        assertMoney("0.00",
                processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(contractual), new HashSet<>(), null, false));
        assertMoney("1.10", transaction.getInterestPortion(CURRENCY));
        assertMoney("0.00", transaction.getPrincipalPortion(CURRENCY));
        assertMoney("1.10", contractual.getInterestPaid(CURRENCY));
        assertEquals(1, transaction.getLoanTransactionToRepaymentScheduleMappings().size());
        assertEquals(FIRST_DUE, contractual.getDueDate());
    }

    @Test
    void finalEmptyScheduleStillFailsEvenWithFutureContractualEvidence() {
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(), new HashSet<>(), null, false));
    }

    @Test
    void firstDueDateFinalPostingCannotExceedContractualInterest() {
        transaction = payment(FIRST_DUE, "0.00", "2.00", "0.00", "0.00");
        assertThrows(GeneralPlatformDomainRuleException.class, () -> processor.handleTransactionAndCharges(transaction, CURRENCY,
                List.of(installment(FIRST_DUE, "1.00")), new HashSet<>(), null, false));
    }

    @ParameterizedTest
    @ValueSource(strings = { "missing-loan", "missing-schedule", "same-day-due", "past-due", "before-disbursement", "missing-disbursement",
            "insufficient-interest" })
    void emptyPrefixRequiresFutureContractualCoverage(final String invalid) {
        switch (invalid) {
            case "missing-loan" -> transaction.updateLoan(null);
            case "missing-schedule" -> when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of());
            case "same-day-due" -> useSchedule(PAYMENT, "130.82");
            case "past-due" -> useSchedule(PAYMENT.minusDays(1), "130.82");
            case "before-disbursement" -> when(loan.getDisbursementDate()).thenReturn(PAYMENT.plusDays(1));
            case "missing-disbursement" -> when(loan.getDisbursementDate()).thenReturn(null);
            case "insufficient-interest" -> useSchedule(FIRST_DUE, "1.09");
        }
        assertThrows(GeneralPlatformDomainRuleException.class, this::recalculate);
    }

    @Test
    void nonemptyPrefixKeepsItsExistingInterestGuard() {
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY,
                        List.of(installment(PAYMENT, "0.00")), new HashSet<>()));
    }

    @ParameterizedTest
    @ValueSource(booleans = { true, false })
    void missingFeesAndPenaltiesCannotBeDeferredAsInterest(final boolean fee) {
        transaction = payment(PAYMENT, "0.00", "1.10", fee ? "0.01" : "0.00", fee ? "0.00" : "0.01");
        assertThrows(GeneralPlatformDomainRuleException.class, this::recalculate);
    }

    @Test
    void loan10EmptyPrefixReturnsDeclaredPrincipalAndFinalPostingMapsTheMixedPayment() {
        final var rows = loan10Schedule();
        transaction = payment(LocalDate.of(2023, 5, 13), "27.37", "98.63", "0.00", "0.00");
        assertMoney("27.37", recalculate());
        assertMoney("98.63", transaction.getSourceExactInterestPortion(CURRENCY));
        for (var row : rows) {
            assertMoney("0.00", row.getPrincipalCompleted(CURRENCY));
            assertMoney("0.00", row.getInterestPaid(CURRENCY));
        }
        assertMoney("0.00", processor.handleTransactionAndCharges(transaction, CURRENCY, rows, new HashSet<>(), null, false));
        assertMoney("27.37", transaction.getPrincipalPortion(CURRENCY));
        assertMoney("98.63", transaction.getInterestPortion(CURRENCY));
        assertMoney("18.95", rows.get(0).getPrincipalCompleted(CURRENCY));
        assertMoney("8.42", rows.get(1).getPrincipalCompleted(CURRENCY));
        assertMoney("98.63", rows.get(0).getInterestPaid(CURRENCY));
        assertMoney("0.00", rows.get(1).getInterestPaid(CURRENCY));
        assertEquals(2, transaction.getLoanTransactionToRepaymentScheduleMappings().size());
        assertEquals(LocalDate.of(2023, 5, 14), rows.get(0).getDueDate());
        assertEquals(LocalDate.of(2023, 6, 14), rows.get(1).getDueDate());
    }

    @Test
    void loan10StillRejectsMixedPaymentWithoutContractualEvidence() {
        loan10Schedule();
        transaction = payment(LocalDate.of(2023, 5, 13), "27.37", "98.63", "0.00", "0.00");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of());
        assertThrows(GeneralPlatformDomainRuleException.class, this::recalculate);
    }

    @Test
    void loan10FinalPostingStillRejectsUnrepresentedPrincipal() {
        final var rows = loan10Schedule();
        transaction = payment(LocalDate.of(2023, 5, 13), "27.37", "98.63", "0.00", "0.00");
        assertMoney("27.37", recalculate());
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(rows.get(0)), new HashSet<>(), null, false));
    }

    @ParameterizedTest
    @ValueSource(strings = { "1036", "1040" })
    void februaryMixedPaymentsDeferOnlyInterestAndMapAcrossTheRequiredInstallments(final String sourceLoan) {
        final var rows = februaryMixedSchedule(sourceLoan);
        final Money principal = transaction.getSourceExactPrincipalPortion(CURRENCY);
        final Money interest = transaction.getSourceExactInterestPortion(CURRENCY);
        assertMoney(principal.getAmount().toPlainString(), recalculate());
        for (var row : rows) {
            assertMoney("0.00", row.getPrincipalCompleted(CURRENCY));
            assertMoney("0.00", row.getInterestPaid(CURRENCY));
        }
        assertMoney("0.00", processor.handleTransactionAndCharges(transaction, CURRENCY, rows, new HashSet<>(), null, false));
        assertMoney(principal.getAmount().toPlainString(), transaction.getPrincipalPortion(CURRENCY));
        assertMoney(interest.getAmount().toPlainString(), transaction.getInterestPortion(CURRENCY));
        assertMoney(rows.get(0).getPrincipal(CURRENCY).getAmount().toPlainString(), rows.get(0).getPrincipalCompleted(CURRENCY));
        assertMoney(sourceLoan.equals("1036") ? "18.52" : "7.31", rows.get(1).getPrincipalCompleted(CURRENCY));
        assertMoney(sourceLoan.equals("1036") ? "0.00" : "0.58", rows.get(2).getPrincipalCompleted(CURRENCY));
        assertMoney(interest.getAmount().toPlainString(), rows.get(0).getInterestPaid(CURRENCY));
        assertMoney("0.00", rows.get(1).getInterestPaid(CURRENCY));
        assertEquals(sourceLoan.equals("1036") ? 2 : 3, transaction.getLoanTransactionToRepaymentScheduleMappings().size());
        assertEquals(LocalDate.of(2025, 3, sourceLoan.equals("1036") ? 15 : 17), rows.get(0).getDueDate());
    }

    @ParameterizedTest
    @ValueSource(strings = { "1036", "1040" })
    void februaryMixedPaymentsStillRequireFutureContractualCoverage(final String sourceLoan) {
        februaryMixedSchedule(sourceLoan);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of());
        assertThrows(GeneralPlatformDomainRuleException.class, this::recalculate);
    }

    @ParameterizedTest
    @ValueSource(strings = { "1036", "1040" })
    void februaryMixedFinalPostingStillRejectsInsufficientPrincipalCapacity(final String sourceLoan) {
        final var rows = februaryMixedSchedule(sourceLoan);
        assertMoney(transaction.getSourceExactPrincipalPortion(CURRENCY).getAmount().toPlainString(), recalculate());
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(rows.get(0)), new HashSet<>(), null, false));
    }

    private List<LoanRepaymentScheduleInstallment> februaryMixedSchedule(final String sourceLoan) {
        final boolean mobileCollection = sourceLoan.equals("1036");
        final LocalDate disbursed = LocalDate.of(2025, 2, 14);
        final LocalDate firstDue = LocalDate.of(2025, 3, mobileCollection ? 15 : 17);
        when(loan.getDisbursementDate()).thenReturn(disbursed);
        final var rows = List.of(
                new LoanRepaymentScheduleInstallment(loan, 1, disbursed, firstDue, new BigDecimal(mobileCollection ? "69.73" : "22.44"),
                        new BigDecimal(mobileCollection ? "25.32" : "151.89"), BigDecimal.ZERO, BigDecimal.ZERO, false, null),
                new LoanRepaymentScheduleInstallment(loan, 2, firstDue, firstDue.plusMonths(1),
                        new BigDecimal(mobileCollection ? "70.58" : "7.31"), new BigDecimal(mobileCollection ? "24.47" : "167.02"),
                        BigDecimal.ZERO, BigDecimal.ZERO, false, null),
                new LoanRepaymentScheduleInstallment(loan, 3, firstDue.plusMonths(1), firstDue.plusMonths(2),
                        new BigDecimal(mobileCollection ? "74.85" : "13.06"), new BigDecimal(mobileCollection ? "20.20" : "161.27"),
                        BigDecimal.ZERO, BigDecimal.ZERO, false, null));
        when(loan.getRepaymentScheduleInstallments()).thenReturn(rows);
        transaction = payment(LocalDate.of(2025, 2, 28), mobileCollection ? "88.25" : "30.33", mobileCollection ? "11.75" : "59.67", "0.00",
                "0.00");
        return rows;
    }

    private List<LoanRepaymentScheduleInstallment> loan10Schedule() {
        final LocalDate disbursed = LocalDate.of(2023, 4, 14);
        final LocalDate firstDue = LocalDate.of(2023, 5, 14);
        when(loan.getDisbursementDate()).thenReturn(disbursed);
        final var rows = List.of(
                new LoanRepaymentScheduleInstallment(loan, 1, disbursed, firstDue, new BigDecimal("18.95"), new BigDecimal("101.92"),
                        BigDecimal.ZERO, BigDecimal.ZERO, false, null),
                new LoanRepaymentScheduleInstallment(loan, 2, firstDue, LocalDate.of(2023, 6, 14), new BigDecimal("19.92"),
                        new BigDecimal("100.95"), BigDecimal.ZERO, BigDecimal.ZERO, false, null));
        when(loan.getRepaymentScheduleInstallments()).thenReturn(rows);
        return rows;
    }

    private void useSchedule(LocalDate due, String interest) {
        final var rows = List.of(installment(due, interest));
        when(loan.getRepaymentScheduleInstallments()).thenReturn(rows);
    }

    private Money recalculate() {
        return processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY, List.of(), new HashSet<>());
    }

    private LoanTransaction payment(LocalDate date, String principal, String interest, String fee, String penalty) {
        BigDecimal p = new BigDecimal(principal), i = new BigDecimal(interest), f = new BigDecimal(fee), n = new BigDecimal(penalty);
        LoanTransaction result = LoanTransaction.repayment(mock(Office.class), Money.of(CURRENCY, p.add(i).add(f).add(n)), null, date,
                new ExternalId("ARISSTO:CRD-MOV:0000005349"));
        result.updateLoan(loan);
        result.markAsSourceExactAllocation(new SourceExactRepaymentAllocation(p, i, f, n));
        return result;
    }

    private LoanRepaymentScheduleInstallment installment(LocalDate due, String interest) {
        return new LoanRepaymentScheduleInstallment(loan, 1, DISBURSED, due, new BigDecimal("42.22"), new BigDecimal(interest),
                BigDecimal.ZERO, BigDecimal.ZERO, false, null);
    }

    private void assertMoney(String expected, Money actual) {
        assertEquals(0, new BigDecimal(expected).compareTo(actual.getAmount()));
    }
}
