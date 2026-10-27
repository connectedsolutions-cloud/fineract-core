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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.*;

import java.math.*;
import java.time.LocalDate;
import java.util.*;
import org.apache.fineract.organisation.monetary.domain.*;
import org.apache.fineract.portfolio.common.domain.DaysInYearType;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanproduct.domain.*;
import org.junit.jupiter.api.Test;

class MigrationAccrualContinuationTest {

    @Test
    void sourceBaselineClipsHistoryAndWholeFreezeDoesNotCatchUpOnResume() {
        try (var money = mockStatic(MoneyHelper.class)) {
            money.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
            money.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
            Loan loan = mock(Loan.class);
            var terms = mock(LoanProductRelatedDetail.class);
            var currency = new MonetaryCurrency("USD", 2, 0);
            when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
            when(terms.getAnnualNominalInterestRate()).thenReturn(new BigDecimal("100"));
            when(terms.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
            when(terms.getInterestCalculationPeriodMethod()).thenReturn(InterestCalculationPeriodMethod.DAILY);
            when(terms.fetchDaysInYearType()).thenReturn(DaysInYearType.DAYS_365);
            when(loan.getLoanTransactions()).thenReturn(List.of());
            var row = new LoanRepaymentScheduleInstallment(loan, 1, day("2026-01-01"), day("2026-02-01"), new BigDecimal("365"),
                    BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, false, null, null);
            var baseline = new LoanRepaymentScheduleInstallment(loan, 2, day("2026-10-18"), day("2026-10-19"), BigDecimal.ZERO,
                    new BigDecimal("12.35"), BigDecimal.ZERO, BigDecimal.ZERO, false, null, null);
            baseline.setAdditional(true);
            baseline.setMigrationMetricBaseline(true);
            row.setPrincipal(BigDecimal.ZERO);
            var future = new LoanRepaymentScheduleInstallment(loan, 3, day("2026-02-01"), day("2026-10-22"), new BigDecimal("365"),
                    BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, false, null, null);
            var rows = List.of(row, baseline, future);
            when(loan.getFreezeHistory())
                    .thenReturn(List.of(new LoanFreezeHistory(loan, LoanFreezeAction.FREEZE, day("2026-10-21"), null, null),
                            new LoanFreezeHistory(loan, LoanFreezeAction.UNFREEZE, day("2026-10-24"), null, null)));
            var calculator = new PostDueAccruedInterestCalculator();
            for (var expected : Map
                    .of("2026-10-19", "0.00", "2026-10-20", "1.00", "2026-10-23", "1.00", "2026-10-24", "2.00", "2026-10-25", "3.00")
                    .entrySet()) {
                assertEquals(new BigDecimal(expected.getValue()),
                        calculator.calculateAccruableThrough(loan, currency, rows, day(expected.getKey())).getAmount());
            }
            baseline.addPostDueInterest(day("2026-10-24"), Money.of(currency, new BigDecimal("2")));
            assertEquals(new BigDecimal("1.00"),
                    calculator.calculateUnmaterializedAccruableThrough(loan, currency, rows, day("2026-10-25")).getAmount());
        }
    }

    @Test
    void moraStartsAtHandoffAndExcludesAllFrozenDays() {
        var calculator = new CredesalDailyMoraCalculator();
        var periods = List.of(new CredesalInterestPausePeriods.Period(day("2026-10-21"), day("2026-10-23")));
        var rows = List.of(new CredesalDailyMoraCalculator.Installment(day("2026-01-01"), new BigDecimal("100"), BigDecimal.ZERO));
        for (var expected : Map.of("2026-10-20", "1.00", "2026-10-23", "1.00", "2026-10-24", "2.00", "2026-10-25", "3.00").entrySet()) {
            assertEquals(new BigDecimal(expected.getValue()), calculator.calculate(day(expected.getKey()), new BigDecimal("100"),
                    new BigDecimal("100"), 100, 0, day("2026-10-19"), new BigDecimal("30"), rows, 2, periods));
        }
    }

    private static LocalDate day(String value) {
        return LocalDate.parse(value);
    }
}
