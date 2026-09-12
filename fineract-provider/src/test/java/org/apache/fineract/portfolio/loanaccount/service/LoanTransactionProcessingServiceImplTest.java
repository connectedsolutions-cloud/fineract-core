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
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.loanaccount.data.OutstandingAmountsDTO;
import org.apache.fineract.portfolio.loanaccount.data.ScheduleGeneratorDTO;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleTransactionProcessorFactory;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl.CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.mapper.LoanTermVariationsMapper;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockedStatic;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class LoanTransactionProcessingServiceImplTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static MockedStatic<MoneyHelper> moneyHelper;

    @Mock
    private LoanRepaymentScheduleTransactionProcessorFactory transactionProcessorFactory;
    @Mock
    private LoanTermVariationsMapper loanMapper;
    @Mock
    private InterestScheduleModelRepositoryWrapper modelRepository;
    @Mock
    private LoanTransactionService loanTransactionService;
    @Mock
    private PostDueAccruedInterestCalculator postDueAccruedInterestCalculator;
    @Mock
    private Loan loan;
    @Mock
    private LoanRepaymentScheduleInstallment installment;
    @Mock
    private ScheduleGeneratorDTO scheduleGeneratorDTO;

    @InjectMocks
    private LoanTransactionProcessingServiceImpl service;

    @BeforeAll
    static void initMoney() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
    }

    @AfterAll
    static void closeMoney() {
        moneyHelper.close();
    }

    @Test
    void prepaymentIncludesUnmaterializedCredesalInterestAfterMaturity() {
        final LocalDate paymentDate = LocalDate.of(2026, 7, 1);
        final List<LoanRepaymentScheduleInstallment> installments = List.of(installment);
        final Money principalOutstanding = Money.of(CURRENCY, new BigDecimal("350.00"));
        final Money interestOutstanding = Money.of(CURRENCY, new BigDecimal("12.08"));
        final Money zero = Money.zero(CURRENCY);
        final Money postMaturityInterest = Money.of(CURRENCY, new BigDecimal("2.42"));

        when(loan.isInterestBearingAndInterestRecalculationEnabled()).thenReturn(false);
        when(loan.isOpen()).thenReturn(true);
        when(loan.transactionProcessingStrategy())
                .thenReturn(CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.STRATEGY_CODE);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(installments);
        when(installment.getDueDate()).thenReturn(paymentDate.minusDays(3));
        when(installment.getPrincipalOutstanding(CURRENCY)).thenReturn(principalOutstanding);
        when(installment.getInterestOutstanding(CURRENCY)).thenReturn(interestOutstanding);
        when(installment.getFeeChargesOutstanding(CURRENCY)).thenReturn(zero);
        when(installment.getPenaltyChargesOutstanding(CURRENCY)).thenReturn(zero);
        when(postDueAccruedInterestCalculator.calculateUnmaterializedAccruableThrough(loan, CURRENCY, installments, paymentDate))
                .thenReturn(postMaturityInterest);

        final OutstandingAmountsDTO result = service.fetchPrepaymentDetail(scheduleGeneratorDTO, paymentDate, loan);

        assertEquals(0, new BigDecimal("14.50").compareTo(result.interest().getAmount()));
        assertEquals(0, new BigDecimal("364.50").compareTo(result.getTotalOutstanding().getAmount()));
    }

    @Test
    void prepaymentDoesNotAddPostDueInterestBeforeContractualMaturity() {
        final LocalDate paymentDate = LocalDate.of(2026, 6, 25);
        final List<LoanRepaymentScheduleInstallment> installments = List.of(installment);
        final Money principalOutstanding = Money.of(CURRENCY, new BigDecimal("350.00"));
        final Money interestOutstanding = Money.of(CURRENCY, new BigDecimal("12.08"));
        final Money zero = Money.zero(CURRENCY);

        when(loan.isInterestBearingAndInterestRecalculationEnabled()).thenReturn(false);
        when(loan.isOpen()).thenReturn(true);
        when(loan.transactionProcessingStrategy())
                .thenReturn(CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.STRATEGY_CODE);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(installments);
        when(installment.getDueDate()).thenReturn(paymentDate.plusDays(3));
        when(installment.getPrincipalOutstanding(CURRENCY)).thenReturn(principalOutstanding);
        when(installment.getInterestOutstanding(CURRENCY)).thenReturn(interestOutstanding);
        when(installment.getFeeChargesOutstanding(CURRENCY)).thenReturn(zero);
        when(installment.getPenaltyChargesOutstanding(CURRENCY)).thenReturn(zero);

        final OutstandingAmountsDTO result = service.fetchPrepaymentDetail(scheduleGeneratorDTO, paymentDate, loan);

        assertEquals(0, new BigDecimal("12.08").compareTo(result.interest().getAmount()));
        verifyNoInteractions(postDueAccruedInterestCalculator);
    }
}
