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
package org.apache.fineract.portfolio.loanaccount.loanschedule.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.monetary.mapper.CurrencyMapper;
import org.apache.fineract.portfolio.loanaccount.data.LoanTermVariationsData;
import org.apache.fineract.portfolio.loanaccount.data.LoanTermVariationsDataWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

class CredesalCumulativeInterestPauseTest {

    @Test
    void partialPauseReducesOnlyInterestAndKeepsTheContractedPrincipal() {
        try (MockedStatic<MoneyHelper> moneyHelper = Mockito.mockStatic(MoneyHelper.class)) {
            moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
            moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
            final MonetaryCurrency currency = new MonetaryCurrency("USD", 2, 1);
            final Money zero = Money.zero(currency);
            final Money principal = Money.of(currency, new BigDecimal("100.00"));
            final Money interest = Money.of(currency, new BigDecimal("10.00"));
            final LocalDate fromDate = LocalDate.of(2026, 6, 1);
            final LocalDate dueDate = fromDate.plusDays(10);
            final LoanTermVariationsData pause = new LoanTermVariationsData(null, 11, fromDate.plusDays(6), BigDecimal.ZERO, dueDate,
                    false);
            final LoanTermVariationsDataWrapper variations = new LoanTermVariationsDataWrapper(new ArrayList<>(List.of(pause)));
            final LoanApplicationTerms terms = mock(LoanApplicationTerms.class);
            final PaymentPeriodsInOneYearCalculator calculator = mock(PaymentPeriodsInOneYearCalculator.class);
            when(terms.getLoanTermVariations()).thenReturn(variations);
            when(terms.calculateTotalInterestForPeriod(any(), any(), anyInt(), any(), any(), any(), any(), any()))
                    .thenReturn(new PrincipalInterest(zero, interest, zero));
            when(terms.calculateTotalPrincipalForPeriod(any(), any(), anyInt(), any(), any())).thenReturn(principal);
            when(terms.adjustPrincipalIfLastRepaymentPeriod(any(), any(), anyInt())).thenReturn(principal);
            final var generator = new CumulativeDecliningBalanceInterestLoanScheduleGenerator(mock(ScheduledDateGenerator.class),
                    calculator, mock(LoanTransactionRepository.class), mock(CurrencyMapper.class));

            final PrincipalInterest result = generator.calculatePrincipalInterestComponentsForPeriod(calculator, BigDecimal.ZERO, zero,
                    zero, zero, zero, Money.of(currency, new BigDecimal("1000.00")), terms, 1, MoneyHelper.getMathContext(),
                    new TreeMap<>(), Map.of(), fromDate, dueDate, List.of());

            assertEquals(0, principal.compareTo(result.principal()));
            assertEquals(0, Money.of(currency, new BigDecimal("5.00")).compareTo(result.interest()));
        }
    }
}
