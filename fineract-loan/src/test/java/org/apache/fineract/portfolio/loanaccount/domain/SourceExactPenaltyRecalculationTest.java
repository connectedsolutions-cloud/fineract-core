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
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
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
import org.apache.fineract.portfolio.common.domain.DaysInYearType;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidBy;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.SourceExactRepaymentAllocation;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.apache.fineract.portfolio.loanproduct.domain.InterestMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

class SourceExactPenaltyRecalculationTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static final LocalDate PAYMENT_DATE = LocalDate.of(2025, 8, 25);
    private static final BigDecimal PENALTY = new BigDecimal("0.26");
    private MockedStatic<MoneyHelper> moneyHelper;
    private CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor processor;
    private Loan loan;
    private LoanCharge charge;
    private LoanTransaction transaction;

    @BeforeEach
    void setUp() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, PAYMENT_DATE)));
        processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), new PostDueAccruedInterestCalculator());
        loan = mock(Loan.class);
        when(loan.getId()).thenReturn(1146L);
        final LoanProductRelatedDetail terms = mock(LoanProductRelatedDetail.class);
        when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
        when(terms.getAnnualNominalInterestRate()).thenReturn(BigDecimal.ZERO);
        when(terms.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        when(terms.getInterestCalculationPeriodMethod()).thenReturn(InterestCalculationPeriodMethod.DAILY);
        when(terms.fetchDaysInYearType()).thenReturn(DaysInYearType.DAYS_365);
        when(loan.getLoanTransactions()).thenReturn(List.of());
        transaction = LoanTransaction.repayment(mock(Office.class), Money.of(CURRENCY, new BigDecimal("15.26")), null, PAYMENT_DATE,
                ExternalId.empty());
        transaction.updateLoan(loan);
        transaction.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(new BigDecimal("10"), new BigDecimal("5"), BigDecimal.ZERO, PENALTY));
        charge = mock(LoanCharge.class);
        when(charge.getLoan()).thenReturn(loan);
        when(charge.isActive()).thenReturn(true);
        when(charge.isPenaltyCharge()).thenReturn(true);
        when(charge.getDueLocalDate()).thenReturn(PAYMENT_DATE);
        final Money penaltyMoney = Money.of(CURRENCY, PENALTY);
        when(charge.getAmountOutstanding(any(MonetaryCurrency.class))).thenReturn(penaltyMoney);
        when(charge.updatePaidAmountBy(any(Money.class), isNull(), any(Money.class))).thenReturn(penaltyMoney);
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
        moneyHelper.close();
    }

    @Test
    void temporaryPrefixDefersOnlyRealDuePenaltyWithoutChangingTheCharge() {
        final LoanRepaymentScheduleInstallment prefix = installment(BigDecimal.ZERO);
        final Money remainder = processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY, List.of(prefix),
                new HashSet<>(List.of(charge)));
        assertMoney("0.00", remainder);
        assertMoney("10.00", transaction.getPrincipalPortion(CURRENCY));
        assertMoney("0.00", transaction.getPenaltyChargesPortion(CURRENCY));
        assertMoney("0.26", transaction.getSourceExactPenaltyChargesPortion(CURRENCY));
        assertMoney("0.00", prefix.getPenaltyChargesCharged(CURRENCY));
        assertEquals(0, transaction.getLoanChargesPaid().size());
        verify(charge, never()).updatePaidAmountBy(any(Money.class), isNull(), any(Money.class));
    }

    @Test
    void finalPostingMustRepresentAndSettleTheEntireDeclaredPenaltyExactlyOnce() {
        processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY, List.of(installment(BigDecimal.ZERO)),
                new HashSet<>(List.of(charge)));
        final Money remainder = processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(installment(PENALTY)),
                new HashSet<>(List.of(charge)), null, false);
        assertMoney("0.00", remainder);
        assertMoney("10.00", transaction.getPrincipalPortion(CURRENCY));
        assertMoney("5.00", transaction.getInterestPortion(CURRENCY));
        assertMoney("0.26", transaction.getPenaltyChargesPortion(CURRENCY));
        assertEquals(1, transaction.getLoanChargesPaid().size());
        verify(charge).updatePaidAmountBy(any(Money.class), isNull(), any(Money.class));
    }

    @Test
    void finalPostingWithMissingSchedulePenaltyStillFailsEvenWithARealCharge() {
        assertThrows(GeneralPlatformDomainRuleException.class, () -> processor.handleTransactionAndCharges(transaction, CURRENCY,
                List.of(installment(BigDecimal.ZERO)), new HashSet<>(List.of(charge)), null, false));
    }

    @ParameterizedTest
    @ValueSource(strings = { "missing", "future", "inactive", "fee", "foreign", "insufficient", "installment", "waived" })
    void temporaryPrefixRejectsUnprovenPenaltyCoverage(final String invalid) {
        if (invalid.equals("future")) {
            when(charge.getDueLocalDate()).thenReturn(PAYMENT_DATE.plusDays(1));
        } else if (invalid.equals("inactive")) {
            when(charge.isActive()).thenReturn(false);
        } else if (invalid.equals("fee")) {
            when(charge.isPenaltyCharge()).thenReturn(false);
        } else if (invalid.equals("foreign")) {
            final Loan other = mock(Loan.class);
            when(other.getId()).thenReturn(999L);
            when(charge.getLoan()).thenReturn(other);
        } else if (invalid.equals("insufficient")) {
            final Money insufficient = Money.of(CURRENCY, new BigDecimal("0.25"));
            when(charge.getAmountOutstanding(any(MonetaryCurrency.class))).thenReturn(insufficient);
        } else if (invalid.equals("installment")) {
            when(charge.isInstalmentFee()).thenReturn(true);
        } else if (invalid.equals("waived")) {
            when(charge.isWaived()).thenReturn(true);
        }
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY,
                        List.of(installment(BigDecimal.ZERO)),
                        invalid.equals("missing") ? new HashSet<>() : new HashSet<>(List.of(charge))));
    }

    @Test
    void recalculationCopyCanUseOnlyItsOriginalPersistedPaidChargeOwnership() {
        final LoanTransaction original = paidOriginal();
        final LoanTransaction copy = LoanTransaction.copyTransactionProperties(original);
        assertEquals(0, copy.getLoanChargesPaid().size());
        final Money remainder = processor.handleRepaymentScheduleForInterestRecalculation(List.of(copy), CURRENCY,
                List.of(installment(BigDecimal.ZERO)), new HashSet<>());
        assertMoney("0.00", remainder);
        assertMoney("0.26", copy.getSourceExactPenaltyChargesPortion(CURRENCY));
        assertEquals(1, original.getLoanChargesPaid().size());
        assertEquals(0, copy.getLoanChargesPaid().size());
        verify(charge, never()).updatePaidAmountBy(any(Money.class), isNull(), any(Money.class));
    }

    @ParameterizedTest
    @ValueSource(strings = { "external-id", "date", "ownership", "amount", "reversed" })
    void copiedTransactionCannotBorrowAnotherPaymentsPaidPenalty(final String invalid) {
        final LoanTransaction original = paidOriginal();
        final LoanTransaction copy = LoanTransaction.copyTransactionProperties(original);
        if (invalid.equals("external-id")) {
            when(loan.getLoanTransactions()).thenReturn(List.of(transaction));
        } else if (invalid.equals("date")) {
            final LoanTransaction differentDate = LoanTransaction.repayment(mock(Office.class), Money.of(CURRENCY, new BigDecimal("15.26")),
                    null, PAYMENT_DATE.minusDays(1), original.getExternalId());
            differentDate.updateLoan(loan);
            differentDate.setId(77L);
            differentDate.markAsSourceExactAllocation(
                    new SourceExactRepaymentAllocation(new BigDecimal("10"), new BigDecimal("5"), BigDecimal.ZERO, PENALTY));
            differentDate.getLoanChargesPaid().add(new LoanChargePaidBy(differentDate, charge, PENALTY, null));
            when(loan.getLoanTransactions()).thenReturn(List.of(differentDate));
        } else if (invalid.equals("ownership")) {
            original.getLoanChargesPaid().clear();
            original.getLoanChargesPaid().add(new LoanChargePaidBy(transaction, charge, PENALTY, null));
        } else if (invalid.equals("amount")) {
            original.getLoanChargesPaid().iterator().next().setAmount(new BigDecimal("0.25"));
        } else if (invalid.equals("reversed")) {
            original.reverse();
        }
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleRepaymentScheduleForInterestRecalculation(List.of(copy), CURRENCY,
                        List.of(installment(BigDecimal.ZERO)), new HashSet<>()));
    }

    private LoanTransaction paidOriginal() {
        final LoanTransaction original = LoanTransaction.repayment(mock(Office.class), Money.of(CURRENCY, new BigDecimal("15.26")), null,
                PAYMENT_DATE, new ExternalId("ARISSTO:CRD-MOV:paid-penalty"));
        original.updateLoan(loan);
        original.setId(76L);
        original.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(new BigDecimal("10"), new BigDecimal("5"), BigDecimal.ZERO, PENALTY));
        original.getLoanChargesPaid().add(new LoanChargePaidBy(original, charge, PENALTY, null));
        when(loan.getLoanTransactions()).thenReturn(List.of(original));
        when(charge.isActive()).thenReturn(false);
        when(charge.isPaid()).thenReturn(true);
        final Money zero = Money.zero(CURRENCY);
        when(charge.getAmountOutstanding(any(MonetaryCurrency.class))).thenReturn(zero);
        return original;
    }

    private LoanRepaymentScheduleInstallment installment(final BigDecimal penalty) {
        return new LoanRepaymentScheduleInstallment(loan, 8, LocalDate.of(2025, 7, 23), LocalDate.of(2025, 8, 23), new BigDecimal("100"),
                new BigDecimal("5"), BigDecimal.ZERO, penalty, false, null, BigDecimal.ZERO);
    }

    private void assertMoney(final String expected, final Money actual) {
        assertEquals(0, new BigDecimal(expected).compareTo(actual.getAmount()));
    }
}
