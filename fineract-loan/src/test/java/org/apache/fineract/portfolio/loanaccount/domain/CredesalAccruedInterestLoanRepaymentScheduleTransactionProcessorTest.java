/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software distributed under the License is
 * distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
package org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
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
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.common.domain.DaysInYearType;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.SourceExactRepaymentAllocation;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.apache.fineract.portfolio.loanproduct.domain.InterestMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

class CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessorTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static final MockedStatic<MoneyHelper> MONEY_HELPER = Mockito.mockStatic(MoneyHelper.class);
    private static final LocalDate DUE_DATE = LocalDate.of(2026, 6, 28);
    private CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor processor;
    private Loan loan;
    private Office office;
    private LoanProductRelatedDetail terms;

    @BeforeAll
    static void initMoney() {
        MONEY_HELPER.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        MONEY_HELPER.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
    }

    @AfterAll
    static void closeMoney() {
        MONEY_HELPER.close();
    }

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 6, 30))));
        processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), new PostDueAccruedInterestCalculator());
        loan = mock(Loan.class);
        office = mock(Office.class);
        terms = mock(LoanProductRelatedDetail.class);
        when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
        when(terms.getAnnualNominalInterestRate()).thenReturn(new BigDecimal("84"));
        when(terms.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        when(terms.getInterestCalculationPeriodMethod()).thenReturn(InterestCalculationPeriodMethod.DAILY);
        when(terms.fetchDaysInYearType()).thenReturn(DaysInYearType.DAYS_365);
        when(loan.getLoanTransactions()).thenReturn(List.of());
    }

    @AfterEach
    void resetContext() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void oneDayLateRepaymentPaysAccruedInterestBeforePrincipal() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("350.00"), new BigDecimal("12.08"));
        final LoanTransaction repayment = repayment(LocalDate.of(2026, 6, 29), new BigDecimal("39.79"));

        processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("12.89", repayment.getInterestPortion(CURRENCY));
        assertMoney("26.90", repayment.getPrincipalPortion(CURRENCY));
        assertEquals(0, new BigDecimal("0.81").compareTo(installment.getPostDueInterestCharged()));
    }

    @Test
    void advanceRemainderPaysNextPrincipalBeforeFutureInstallmentFee() {
        final LoanRepaymentScheduleInstallment firstInstallment = installment(1, LocalDate.of(2026, 6, 13), DUE_DATE,
                new BigDecimal("24.04"), new BigDecimal("12.08"), new BigDecimal("0.21"));
        final LoanRepaymentScheduleInstallment secondInstallment = installment(2, DUE_DATE, LocalDate.of(2026, 7, 13),
                new BigDecimal("325.96"), new BigDecimal("11.25"), new BigDecimal("0.20"));
        final LoanTransaction repayment = repayment(LocalDate.of(2026, 6, 29), new BigDecimal("40.00"));

        processor.processTransaction(repayment, CURRENCY, List.of(firstInstallment, secondInstallment), new HashSet<>(), null);

        assertMoney("26.90", repayment.getPrincipalPortion(CURRENCY));
        assertMoney("12.89", repayment.getInterestPortion(CURRENCY));
        assertMoney("0.21", repayment.getFeeChargesPortion(CURRENCY));
        assertMoney("0.00", secondInstallment.getFeeChargesPaid(CURRENCY));
    }

    @Test
    void replayResetRemovesPreviouslyMaterializedPostDueInterest() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("350.00"), new BigDecimal("12.08"));
        processor.processTransaction(repayment(LocalDate.of(2026, 6, 29), new BigDecimal("39.79")), CURRENCY, List.of(installment),
                new HashSet<>(), null);

        installment.resetDerivedComponents();

        assertMoney("12.08", installment.getInterestCharged(CURRENCY));
        assertNull(installment.getPostDueInterestCharged());
    }

    @Test
    void onDueDateDoesNotMaterializeAdditionalInterest() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("350.00"), new BigDecimal("12.08"));
        final LoanTransaction repayment = repayment(DUE_DATE, new BigDecimal("39.79"));

        processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("12.08", repayment.getInterestPortion(CURRENCY));
        assertNull(installment.getPostDueInterestCharged());
    }

    @Test
    void laterInstallmentDueDateDoesNotDuplicateScheduledInterest() {
        final LoanRepaymentScheduleInstallment firstInstallment = installment(1, LocalDate.of(2026, 5, 28), DUE_DATE,
                new BigDecimal("24.04"), new BigDecimal("12.08"));
        final LoanRepaymentScheduleInstallment secondInstallment = installment(2, DUE_DATE, LocalDate.of(2026, 7, 13),
                new BigDecimal("24.87"), new BigDecimal("11.25"));
        final LoanTransaction repayment = repayment(LocalDate.of(2026, 7, 13), new BigDecimal("72.24"));

        processor.processTransaction(repayment, CURRENCY, List.of(firstInstallment, secondInstallment), new HashSet<>(), null);

        assertMoney("23.33", repayment.getInterestPortion(CURRENCY));
        assertNull(firstInstallment.getPostDueInterestCharged());
        assertNull(secondInstallment.getPostDueInterestCharged());
    }

    @Test
    void laterRepaymentAccruesOnlySincePreviousLateRepayment() {
        final LoanTransaction previousRepayment = repayment(LocalDate.of(2026, 6, 29), new BigDecimal("39.79"));
        when(loan.getLoanTransactions()).thenReturn(List.of(previousRepayment));
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("323.10"), BigDecimal.ZERO);
        final LoanTransaction repayment = repayment(LocalDate.of(2026, 6, 30), new BigDecimal("10.00"));

        processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("0.74", repayment.getInterestPortion(CURRENCY));
        assertMoney("9.26", repayment.getPrincipalPortion(CURRENCY));
    }

    @Test
    void periodicAccrualUsesActualOutstandingPrincipalAfterDueDate() {
        final LoanRepaymentScheduleInstallment firstInstallment = installment(1, LocalDate.of(2026, 6, 13), DUE_DATE,
                new BigDecimal("26.90"), new BigDecimal("12.08"));
        final LoanRepaymentScheduleInstallment secondInstallment = installment(2, DUE_DATE, LocalDate.of(2026, 7, 13),
                new BigDecimal("323.10"), new BigDecimal("11.25"));

        final Money accrued = new PostDueAccruedInterestCalculator().calculateAccruableThrough(loan, CURRENCY,
                List.of(firstInstallment, secondInstallment), LocalDate.of(2026, 6, 29));

        assertMoney("0.81", accrued);
    }

    @Test
    void periodicAccrualSegmentsActualPrincipalAcrossEarlierRepayments() {
        final LoanTransaction previousRepayment = repayment(LocalDate.of(2026, 6, 29), new BigDecimal("39.79"));
        previousRepayment.updateComponents(Money.of(CURRENCY, new BigDecimal("26.90")), Money.of(CURRENCY, new BigDecimal("12.89")),
                Money.zero(CURRENCY), Money.zero(CURRENCY));
        when(loan.getLoanTransactions()).thenReturn(List.of(previousRepayment));
        final LoanRepaymentScheduleInstallment firstInstallment = installment(1, LocalDate.of(2026, 6, 13), DUE_DATE, BigDecimal.ZERO,
                BigDecimal.ZERO);
        final LoanRepaymentScheduleInstallment secondInstallment = installment(2, DUE_DATE, LocalDate.of(2026, 7, 13),
                new BigDecimal("323.10"), BigDecimal.ZERO);

        final Money accrued = new PostDueAccruedInterestCalculator().calculateAccruableThrough(loan, CURRENCY,
                List.of(firstInstallment, secondInstallment), LocalDate.of(2026, 6, 30));

        assertMoney("1.55", accrued);
    }

    @Test
    void flatInterestLoanDoesNotReceiveDecliningBalancePostDueInterest() {
        when(terms.getInterestMethod()).thenReturn(InterestMethod.FLAT);
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("350.00"), new BigDecimal("12.08"));
        final LoanTransaction repayment = repayment(LocalDate.of(2026, 6, 29), new BigDecimal("39.79"));

        processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("12.08", repayment.getInterestPortion(CURRENCY));
        assertNull(installment.getPostDueInterestCharged());
    }

    @Test
    void sourceExactRepaymentPreservesComponentsEvenWhenNativeOrderWouldPayFee() {
        final LoanRepaymentScheduleInstallment firstInstallment = installment(1, LocalDate.of(2026, 5, 28), DUE_DATE,
                new BigDecimal("12.01"), new BigDecimal("1.15"), new BigDecimal("0.06"));
        final LoanRepaymentScheduleInstallment secondInstallment = installment(2, DUE_DATE, LocalDate.of(2026, 7, 28),
                new BigDecimal("12.15"), new BigDecimal("1.01"), new BigDecimal("0.05"));
        final LoanTransaction repayment = repayment(DUE_DATE, new BigDecimal("13.18"));
        repayment.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(new BigDecimal("12.03"), new BigDecimal("1.15"), BigDecimal.ZERO, BigDecimal.ZERO));

        processor.processTransaction(repayment, CURRENCY, List.of(firstInstallment, secondInstallment), new HashSet<>(), null);

        assertMoney("12.03", repayment.getPrincipalPortion(CURRENCY));
        assertMoney("1.15", repayment.getInterestPortion(CURRENCY));
        assertMoney("0.00", repayment.getFeeChargesPortion(CURRENCY));
        assertMoney("0.02", secondInstallment.getPrincipalCompleted(CURRENCY));
        assertMoney("0.00", firstInstallment.getFeeChargesPaid(CURRENCY));
        assertEquals(2, repayment.getLoanTransactionToRepaymentScheduleMappings().size());

        final LoanTransaction replayCopy = LoanTransaction.copyTransactionProperties(repayment);
        assertTrue(replayCopy.isSourceExactAllocation());
        assertMoney("12.03", replayCopy.getSourceExactPrincipalPortion(CURRENCY));
        assertMoney("1.15", replayCopy.getSourceExactInterestPortion(CURRENCY));
    }

    @Test
    void sourceExactRepaymentRejectsAComponentTheScheduleCannotRepresent() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("12.01"), new BigDecimal("1.15"));
        final LoanTransaction repayment = repayment(DUE_DATE, new BigDecimal("2.00"));
        repayment.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(BigDecimal.ZERO, new BigDecimal("2.00"), BigDecimal.ZERO, BigDecimal.ZERO));

        assertThrows(RuntimeException.class,
                () -> processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null));
    }

    @Test
    void sourceExactLateRepaymentMaterializesOnlyTheMissingHistoricalPostDueInterest() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("12.01"), new BigDecimal("1.15"));
        final LoanTransaction repayment = repayment(DUE_DATE.plusDays(1), new BigDecimal("2.00"));
        repayment.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(BigDecimal.ZERO, new BigDecimal("2.00"), BigDecimal.ZERO, BigDecimal.ZERO));

        processor.processTransaction(repayment, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("2.00", repayment.getInterestPortion(CURRENCY));
        assertMoney("2.00", installment.getInterestCharged(CURRENCY));
        assertMoney("0.85", Money.of(CURRENCY, installment.getPostDueInterestCharged()));
    }

    @Test
    void sourceExactComponentReallocationMovesInterestOutstandingToPrincipalAtomically() {
        final LoanRepaymentScheduleInstallment installment = installment(new BigDecimal("20.00"), BigDecimal.ZERO);
        final LoanTransaction reallocation = repayment(DUE_DATE, BigDecimal.ZERO);
        reallocation.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(new BigDecimal("2.15"), new BigDecimal("-2.15"), BigDecimal.ZERO, BigDecimal.ZERO));
        reallocation.markAsSourceExactComponentReallocation("ARISSTO", "0000005037,0000005038", "0000005039");

        processor.processTransaction(reallocation, CURRENCY, List.of(installment), new HashSet<>(), null);

        assertMoney("2.15", reallocation.getPrincipalPortion(CURRENCY));
        assertMoney("-2.15", reallocation.getInterestPortion(CURRENCY));
        assertMoney("17.85", installment.getPrincipalOutstanding(CURRENCY));
        assertMoney("2.15", installment.getInterestOutstanding(CURRENCY));
        assertEquals(1, reallocation.getLoanTransactionToRepaymentScheduleMappings().size());
        final LoanTransaction replayCopy = LoanTransaction.copyTransactionProperties(reallocation);
        assertTrue(replayCopy.isSourceExactComponentReallocation());
        assertEquals("0000005037,0000005038", replayCopy.getSourceExactReversalMovementIds());
        assertEquals("0000005039", replayCopy.getSourceExactRepaymentMovementId());
    }

    private LoanRepaymentScheduleInstallment installment(final BigDecimal principal, final BigDecimal interest) {
        return installment(1, LocalDate.of(2026, 5, 28), DUE_DATE, principal, interest);
    }

    private LoanRepaymentScheduleInstallment installment(final int installmentNumber, final LocalDate fromDate, final LocalDate dueDate,
            final BigDecimal principal, final BigDecimal interest) {
        return installment(installmentNumber, fromDate, dueDate, principal, interest, BigDecimal.ZERO);
    }

    private LoanRepaymentScheduleInstallment installment(final int installmentNumber, final LocalDate fromDate, final LocalDate dueDate,
            final BigDecimal principal, final BigDecimal interest, final BigDecimal fees) {
        return new LoanRepaymentScheduleInstallment(loan, installmentNumber, fromDate, dueDate, principal, interest, fees, BigDecimal.ZERO,
                false, null, BigDecimal.ZERO);
    }

    private LoanTransaction repayment(final LocalDate date, final BigDecimal amount) {
        final LoanTransaction repayment = LoanTransaction.repayment(office, Money.of(CURRENCY, amount), null, date, ExternalId.empty());
        repayment.updateLoan(loan);
        return repayment;
    }

    private void assertMoney(final String expected, final Money actual) {
        assertEquals(0, new BigDecimal(expected).compareTo(actual.getAmount()));
    }
}
