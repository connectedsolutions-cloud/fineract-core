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

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.*;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.charge.domain.Charge;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;

class FinalLoanMetricsTest {

    private static final LocalDate SOURCE = LocalDate.of(2026, 10, 19);

    @Test
    void alignsAllEightInBothDirectionsAndToZeroWithoutChangingTransactions() {
        try (MockedStatic<MoneyHelper> money = mockStatic(MoneyHelper.class)) {
            money.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
            money.when(MoneyHelper::getMathContext).thenReturn(new MathContext(12, RoundingMode.HALF_EVEN));
            Loan loan = mock(Loan.class);
            var currency = new MonetaryCurrency("USD", 2, 0);
            when(loan.getCurrency()).thenReturn(currency);
            when(loan.getStatus()).thenReturn(LoanStatus.ACTIVE);
            when(loan.getId()).thenReturn(42L);
            var detail = mock(LoanProductRelatedDetail.class);
            var originalPrincipal = Money.of(currency, new BigDecimal("200"));
            when(detail.getPrincipal()).thenReturn(originalPrincipal);
            when(loan.getLoanRepaymentScheduleDetail()).thenReturn(detail);
            var rows = new ArrayList<LoanRepaymentScheduleInstallment>();
            rows.add(new LoanRepaymentScheduleInstallment(loan, 1, SOURCE.minusDays(30), SOURCE.minusDays(5), new BigDecimal("100"),
                    new BigDecimal("10"), BigDecimal.ZERO, BigDecimal.ZERO, false, null, null));
            rows.add(new LoanRepaymentScheduleInstallment(loan, 2, SOURCE.minusDays(5), SOURCE.plusDays(20), new BigDecimal("100"),
                    new BigDecimal("15"), BigDecimal.ZERO, BigDecimal.ZERO, false, null, null));
            rows.getFirst().setPrincipalCompleted(new BigDecimal("20"));
            rows.getFirst().setInterestPaid(new BigDecimal("2"));
            when(loan.getRepaymentScheduleInstallments()).thenReturn(rows);
            doAnswer(i -> {
                rows.add(i.getArgument(0));
                return null;
            }).when(loan).addLoanRepaymentScheduleInstallment(any());
            Set<LoanCharge> charges = new HashSet<>();
            when(loan.getLoanCharges()).thenReturn(charges);
            when(loan.getActiveCharges()).thenReturn(charges);
            doAnswer(i -> {
                charges.add(i.getArgument(0));
                return null;
            }).when(loan).addCharge(any());
            var summary = LoanSummary.create(BigDecimal.ZERO);
            when(loan.getSummary()).thenReturn(summary);
            summary.updateSummary(currency, detail.getPrincipal(), rows, charges, Money.zero(currency), Money.zero(currency));
            Charge insurance = mock(Charge.class), penalty = mock(Charge.class);
            when(insurance.getId()).thenReturn(3L);
            when(penalty.getId()).thenReturn(4L);
            var ids = Set.of(3L, 5L);
            var high = targets("80", "140", "40", "20", "30", "7", "10", "5");
            FinalLoanMetrics.apply(loan, SOURCE, high, ids, insurance, penalty);
            assertEquals(FinalLoanMetrics.normalize(high), FinalLoanMetrics.read(loan, SOURCE, ids));
            var low = targets("10", "100", "2", "1", "10", "0.50", "1", "0.25");
            FinalLoanMetrics.apply(loan, SOURCE, low, ids, insurance, penalty);
            assertEquals(FinalLoanMetrics.normalize(low), FinalLoanMetrics.read(loan, SOURCE, ids));
            int count = rows.size();
            FinalLoanMetrics.apply(loan, SOURCE, low, ids, insurance, penalty);
            assertEquals(count, rows.size());
            var zero = targets("0", "0", "0", "0", "0", "0", "0", "0");
            FinalLoanMetrics.apply(loan, SOURCE, zero, ids, insurance, penalty);
            assertEquals(FinalLoanMetrics.normalize(zero), FinalLoanMetrics.read(loan, SOURCE, ids));
            verify(loan, never()).getLoanTransactions();
            assertTrue(rows.stream().anyMatch(LoanRepaymentScheduleInstallment::isMigrationMetricBaseline));
        }
    }

    @Test
    void rejectsIncompleteNegativeFractionalAndInconsistentVectors() {
        assertThrows(IllegalArgumentException.class, () -> FinalLoanMetrics.validate(Map.of()));
        assertThrows(IllegalArgumentException.class, () -> FinalLoanMetrics.validate(targets("-1", "1", "0", "0", "0", "0", "0", "0")));
        assertThrows(IllegalArgumentException.class, () -> FinalLoanMetrics.validate(targets("0", "1", "0.001", "0", "0", "0", "0", "0")));
        assertThrows(IllegalArgumentException.class, () -> FinalLoanMetrics.validate(targets("0", "1", "0", "0", "2", "0", "0", "0")));
    }

    static Map<String, BigDecimal> targets(String... values) {
        Map<String, BigDecimal> map = new LinkedHashMap<>();
        for (int i = 0; i < values.length; i++)
            map.put(FinalLoanMetrics.KEYS.get(i), new BigDecimal(values[i]));
        return map;
    }
}
