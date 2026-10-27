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
import static org.mockito.Mockito.*;

import java.math.*;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.organisation.monetary.domain.*;
import org.apache.fineract.portfolio.loanaccount.data.AccrualPeriodsData;
import org.apache.fineract.portfolio.loanaccount.domain.*;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleGenerator;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class ReconciledLoanAccrualTest {

    @Test
    void firstNativeDayMakesNewInterestPostableWithoutRepostingTheSourceOpening() {
        check("0.43", "0.00", "0.43");
    }

    @Test
    void laterNativeDaySubtractsOnlyNativeRecognizedInterest() {
        check("0.86", "0.43", "0.43");
    }

    private void check(String cumulative, String alreadyPosted, String newAmount) {
        try (var money = mockStatic(MoneyHelper.class)) {
            money.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
            money.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
            var currency = new MonetaryCurrency("USD", 2, 0);
            Loan loan = mock(Loan.class);
            when(loan.transactionProcessingStrategy()).thenReturn("credesal-accrued-interest-first-strategy");
            var sourceDay = LocalDate.of(2026, 10, 19);
            var till = sourceDay.plusDays(2);
            var anchor = new LoanRepaymentScheduleInstallment(loan, 1, sourceDay.minusDays(1), sourceDay, BigDecimal.ZERO,
                    new BigDecimal("297.68"), BigDecimal.ZERO, BigDecimal.ZERO, false, null, null);
            anchor.setAdditional(true);
            anchor.setMigrationMetricBaseline(true);
            anchor.setMigrationInterestForecast(BigDecimal.ZERO);
            when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of(anchor));
            var source = mock(LoanTransaction.class);
            when(source.isNotReversed()).thenReturn(true);
            when(source.isAccrual()).thenReturn(true);
            when(source.getTransactionDate()).thenReturn(sourceDay);
            var nativeAccrual = mock(LoanTransaction.class);
            when(nativeAccrual.isNotReversed()).thenReturn(true);
            when(nativeAccrual.isAccrual()).thenReturn(true);
            when(nativeAccrual.getTransactionDate()).thenReturn(sourceDay.plusDays(1));
            var posted = Money.of(currency, new BigDecimal(alreadyPosted));
            when(nativeAccrual.getInterestPortion(currency)).thenReturn(posted);
            when(loan.getLoanTransactions()).thenReturn(List.of(source, nativeAccrual));
            var calc = mock(PostDueAccruedInterestCalculator.class);
            var amount = Money.of(currency, new BigDecimal(cumulative));
            when(calc.calculateAccruableThrough(loan, currency, List.of(anchor), till)).thenReturn(amount);
            var service = mock(LoanAccrualsProcessingServiceImpl.class, CALLS_REAL_METHODS);
            ReflectionTestUtils.setField(service, "postDueAccruedInterestCalculator", calc);
            var periods = AccrualPeriodsData.create(List.of(anchor), 1, currency);
            ReflectionTestUtils.invokeMethod(service, "addInterestAccrual", loan, till, mock(LoanScheduleGenerator.class), anchor, periods);
            var period = periods.getPeriodByInstallmentNumber(1);
            assertEquals(new BigDecimal(newAmount), period.getInterestAccruable().minus(period.getInterestAccrued()).getAmount());
            verify(source, never()).getInterestPortion(currency);
        }
    }
}
