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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.charge.domain.ChargeCalculationType;
import org.apache.fineract.portfolio.delinquency.service.DelinquencyReadPlatformService;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanInstallmentCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanLifecycleStateMachine;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;

class LoanChargeServiceOutstandingPrincipalTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 0);
    private static final MockedStatic<MoneyHelper> MONEY_HELPER = mockStatic(MoneyHelper.class);

    private final LoanChargeService underTest = new LoanChargeService(mock(LoanChargeValidator.class),
            mock(LoanTransactionProcessingService.class), mock(LoanLifecycleStateMachine.class), mock(LoanBalanceService.class),
            mock(DelinquencyReadPlatformService.class));

    @BeforeAll
    static void setUpMoney() {
        MONEY_HELPER.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        MONEY_HELPER.when(MoneyHelper::getMathContext).thenReturn(new MathContext(12, RoundingMode.HALF_EVEN));
    }

    @AfterAll
    static void tearDownMoney() {
        MONEY_HELPER.close();
    }

    @Test
    void calculatesDebtInsuranceFromDecliningOpeningPrincipal() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("350.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment first = installment("26.90");
        final LoanRepaymentScheduleInstallment second = installment("28.66");
        final LoanRepaymentScheduleInstallment third = installment("30.33");
        final LoanRepaymentScheduleInstallment fourth = installment("264.11");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(first, second, third, fourth));

        assertEquals(new BigDecimal("350.00"), underTest.calculateOpeningOutstandingPrincipal(loan, first).getAmount());
        assertEquals(new BigDecimal("323.10"), underTest.calculateOpeningOutstandingPrincipal(loan, second).getAmount());
        assertEquals(new BigDecimal("294.44"), underTest.calculateOpeningOutstandingPrincipal(loan, third).getAmount());
        assertEquals(new BigDecimal("264.11"), underTest.calculateOpeningOutstandingPrincipal(loan, fourth).getAmount());

        assertEquals(new BigDecimal("0.74"), underTest.calculatePerInstallmentChargeAmount(loan,
                ChargeCalculationType.PERCENT_OF_OUTSTANDING_PRINCIPAL, new BigDecimal("0.06")));
    }

    @Test
    void appliesNormalCurrencyRoundingWithoutArisstoUpwardBias() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("900.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment installment = installment("900.00");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(installment));

        assertEquals(new BigDecimal("0.54"), underTest.calculatePerInstallmentChargeAmount(loan,
                ChargeCalculationType.PERCENT_OF_OUTSTANDING_PRINCIPAL, new BigDecimal("0.06")));
    }

    @Test
    void usesScheduledOpeningPrincipalWhenEarlierInstallmentsAreCompleted() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("180.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment first = installment("100.00", "0.00");
        final LoanRepaymentScheduleInstallment second = installment("80.00");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(first, second));

        assertEquals(new BigDecimal("180.00"), underTest.calculateOpeningOutstandingPrincipal(loan, first).getAmount());
        assertEquals(new BigDecimal("80.00"), underTest.calculateOpeningOutstandingPrincipal(loan, second).getAmount());
    }

    @Test
    void usesLoanPrincipalWhileScheduleIsStillBeingGenerated() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("350.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment first = installment("24.04");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(first));

        assertEquals(new BigDecimal("350.00"), underTest.calculateOpeningOutstandingPrincipal(loan, first).getAmount());
    }

    @Test
    void excludesNonRepaymentInstallmentsFromDebtInsurance() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("100.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment downPayment = installment("50.00");
        when(downPayment.isDownPayment()).thenReturn(true);
        final LoanRepaymentScheduleInstallment repayment = installment("100.00");
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(downPayment, repayment));

        assertEquals(new BigDecimal("0.00"), underTest.calculateOpeningOutstandingPrincipal(loan, downPayment).getAmount());
    }

    @Test
    void appliesDebtInsuranceOnlyFromTheChargeCutoverDate() {
        final LoanCharge loanCharge = mock(LoanCharge.class);
        when(loanCharge.getChargeCalculation()).thenReturn(ChargeCalculationType.PERCENT_OF_OUTSTANDING_PRINCIPAL);
        when(loanCharge.getSubmittedOnDate()).thenReturn(LocalDate.of(2026, 8, 27));

        final LoanRepaymentScheduleInstallment historical = installment("100.00");
        when(historical.getDueDate()).thenReturn(LocalDate.of(2026, 8, 20));
        final LoanRepaymentScheduleInstallment future = installment("100.00");
        when(future.getDueDate()).thenReturn(LocalDate.of(2026, 8, 28));

        assertFalse(underTest.isInstallmentChargeApplicable(loanCharge, historical));
        assertTrue(underTest.isInstallmentChargeApplicable(loanCharge, future));
    }

    @Test
    void keepsExistingInstallmentChargeBehaviorWhenNoCutoverDateIsConfigured() {
        final LoanCharge loanCharge = mock(LoanCharge.class);
        when(loanCharge.getChargeCalculation()).thenReturn(ChargeCalculationType.PERCENT_OF_OUTSTANDING_PRINCIPAL);
        when(loanCharge.getSubmittedOnDate()).thenReturn(null);

        final LoanRepaymentScheduleInstallment historical = installment("100.00");
        when(historical.getDueDate()).thenReturn(LocalDate.of(2020, 1, 31));

        assertTrue(underTest.isInstallmentChargeApplicable(loanCharge, historical));
    }

    @Test
    void generatesOnlyPostCutoverInstallmentChargesAndUpdatesLoanChargeTotals() {
        final Loan loan = mock(Loan.class);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        final Money loanPrincipal = Money.of(CURRENCY, new BigDecimal("200.00"));
        when(loan.getPrincipal()).thenReturn(loanPrincipal);

        final LoanRepaymentScheduleInstallment historical = installment("100.00");
        when(historical.getDueDate()).thenReturn(LocalDate.of(2026, 8, 20));
        final LoanRepaymentScheduleInstallment future = installment("100.00");
        when(future.getDueDate()).thenReturn(LocalDate.of(2026, 8, 28));
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(historical, future));

        final LoanCharge loanCharge = mock(LoanCharge.class);
        final Set<LoanInstallmentCharge> installmentCharges = new HashSet<>();
        when(loanCharge.getLoan()).thenReturn(loan);
        when(loanCharge.isInstalmentFee()).thenReturn(true);
        when(loanCharge.getChargeCalculation()).thenReturn(ChargeCalculationType.PERCENT_OF_OUTSTANDING_PRINCIPAL);
        when(loanCharge.getPercentage()).thenReturn(new BigDecimal("0.06"));
        when(loanCharge.getSubmittedOnDate()).thenReturn(LocalDate.of(2026, 8, 27));
        when(loanCharge.getLoanInstallmentCharge()).thenReturn(installmentCharges);
        when(loanCharge.calculateOutstanding()).thenReturn(new BigDecimal("0.06"));

        underTest.updateInstallmentCharges(loanCharge);

        assertEquals(1, installmentCharges.size());
        assertEquals(new BigDecimal("0.06"), installmentCharges.iterator().next().getAmount());
        verify(loanCharge).setAmount(new BigDecimal("0.06"));
        verify(loanCharge).setAmountOutstanding(new BigDecimal("0.06"));
    }

    private LoanRepaymentScheduleInstallment installment(final String principal) {
        return installment(principal, principal);
    }

    private LoanRepaymentScheduleInstallment installment(final String principal, final String principalOutstanding) {
        final LoanRepaymentScheduleInstallment installment = mock(LoanRepaymentScheduleInstallment.class);
        final Money principalMoney = Money.of(CURRENCY, new BigDecimal(principal));
        final Money principalOutstandingMoney = Money.of(CURRENCY, new BigDecimal(principalOutstanding));
        when(installment.getPrincipal(CURRENCY)).thenReturn(principalMoney);
        when(installment.getPrincipalOutstanding(CURRENCY)).thenReturn(principalOutstandingMoney);
        when(installment.getInstallmentCharges()).thenReturn(new HashSet<>());
        return installment;
    }
}
