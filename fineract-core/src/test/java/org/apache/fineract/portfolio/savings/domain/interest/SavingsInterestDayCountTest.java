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
package org.apache.fineract.portfolio.savings.domain.interest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.infrastructure.core.domain.LocalDateInterval;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.savings.SavingsCompoundingInterestPeriodType;
import org.apache.fineract.portfolio.savings.SavingsInterestCalculationDaysInYearType;
import org.apache.fineract.portfolio.savings.SavingsInterestCalculationType;
import org.apache.fineract.portfolio.savings.service.SavingsEnumerations;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

class SavingsInterestDayCountTest {

    private static final MathContext MC = MathContext.DECIMAL64;
    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, null);
    private static MockedStatic<MoneyHelper> moneyHelper;

    @BeforeAll
    static void setUp() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(MC);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2024, 1, 2))));
    }

    @AfterAll
    static void tearDown() {
        moneyHelper.close();
        ThreadLocalContextUtil.reset();
    }

    @Test
    void shouldResolveActualSavingsEnum() {
        assertEquals(SavingsInterestCalculationDaysInYearType.ACTUAL, SavingsInterestCalculationDaysInYearType.fromInt(1));
        assertTrue(SavingsInterestCalculationDaysInYearType.ACTUAL.isActual());
        assertTrue(Arrays.asList(SavingsInterestCalculationDaysInYearType.integerValues()).contains(1));

        final EnumOptionData option = SavingsEnumerations
                .interestCalculationDaysInYearType(SavingsInterestCalculationDaysInYearType.ACTUAL);
        assertEquals(1L, option.getId());
        assertEquals("savingsInterestCalculationDaysInYearType.actual", option.getCode());
        assertEquals("Actual", option.getValue());
    }

    @Test
    void shouldUseCalendarYearLength() {
        assertDecimalEquals(BigDecimal.valueOf(5).divide(BigDecimal.valueOf(365), MC),
                SavingsInterestDayCount.yearFraction(LocalDate.of(2023, 10, 20), 5, SavingsInterestCalculationDaysInYearType.ACTUAL));
        assertDecimalEquals(BigDecimal.valueOf(5).divide(BigDecimal.valueOf(366), MC),
                SavingsInterestDayCount.yearFraction(LocalDate.of(2024, 10, 20), 5, SavingsInterestCalculationDaysInYearType.ACTUAL));
    }

    @Test
    void shouldSplitActualYearFractionAtCalendarYearBoundary() {
        final BigDecimal expected = BigDecimal.valueOf(2).divide(BigDecimal.valueOf(365), MC)
                .add(BigDecimal.valueOf(2).divide(BigDecimal.valueOf(366), MC));

        assertDecimalEquals(expected,
                SavingsInterestDayCount.yearFraction(LocalDate.of(2023, 12, 30), 4, SavingsInterestCalculationDaysInYearType.ACTUAL));
    }

    @Test
    void shouldReproduceVerifiedArisstoLeapYearAccrual() {
        final EndOfDayBalance balance = balance(LocalDate.of(2024, 10, 20), "6280.00", 5);

        final BigDecimal interest = balance.calculateInterestOnBalance(BigDecimal.ZERO, new BigDecimal("0.10"),
                SavingsInterestCalculationDaysInYearType.ACTUAL, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);

        assertEquals(new BigDecimal("8.579234973"), interest);
        assertEquals(new BigDecimal("8.58"), interest.setScale(2, RoundingMode.HALF_EVEN));
    }

    @Test
    void shouldPreserveFixed365Arithmetic() {
        final EndOfDayBalance balance = balance(LocalDate.of(2024, 10, 20), "6280.00", 5);
        final BigDecimal multiplicand = BigDecimal.ONE.divide(BigDecimal.valueOf(365), MC);
        final BigDecimal dailyInterestRate = new BigDecimal("0.10").multiply(multiplicand, MC);
        final BigDecimal periodicInterestRate = dailyInterestRate.multiply(BigDecimal.valueOf(5), MC);
        final BigDecimal expected = new BigDecimal("6280.00").multiply(periodicInterestRate, MC).setScale(9, RoundingMode.HALF_EVEN);

        final BigDecimal actual = balance.calculateInterestOnBalance(BigDecimal.ZERO, new BigDecimal("0.10"),
                SavingsInterestCalculationDaysInYearType.DAYS_365, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);

        assertEquals(expected, actual);
    }

    @Test
    void shouldWeightAverageDailyBalancesAcrossCalendarYears() {
        final List<EndOfDayBalance> balances = List.of(balance(LocalDate.of(2023, 12, 30), "1000.00", 2),
                balance(LocalDate.of(2024, 1, 1), "1000.00", 2));
        final BigDecimal expectedYearFraction = BigDecimal.valueOf(2).divide(BigDecimal.valueOf(365), MC)
                .add(BigDecimal.valueOf(2).divide(BigDecimal.valueOf(366), MC));
        final BigDecimal expected = new BigDecimal("1000.00").multiply(expectedYearFraction, MC).multiply(new BigDecimal("0.10"), MC)
                .setScale(9, RoundingMode.HALF_EVEN);

        final BigDecimal actual = SavingsInterestDayCount.calculateAverageDailyBalanceInterest(balances, BigDecimal.ZERO,
                new BigDecimal("0.10"), SavingsInterestCalculationDaysInYearType.ACTUAL, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);

        assertEquals(expected, actual);
    }

    @Test
    void shouldSplitDailyCompoundingAtCalendarYearBoundary() {
        final BigDecimal factor2023 = BigDecimal.ONE.add(new BigDecimal("0.10").divide(BigDecimal.valueOf(365), MC));
        final BigDecimal factor2024 = BigDecimal.ONE.add(new BigDecimal("0.10").divide(BigDecimal.valueOf(366), MC));
        final BigDecimal expected = BigDecimal.valueOf(Math.pow(factor2023.doubleValue(), 2) * Math.pow(factor2024.doubleValue(), 2));

        final BigDecimal actual = SavingsInterestDayCount.dailyCompoundingFactor(new BigDecimal("0.10"), LocalDate.of(2023, 12, 30), 4,
                SavingsInterestCalculationDaysInYearType.ACTUAL);

        assertEquals(expected, actual);
    }

    @Test
    void shouldCalculateActualAcrossYearBoundaryThroughPostingPeriod() {
        final PostingPeriod period = postingPeriod(SavingsCompoundingInterestPeriodType.ANNUAL, 2);
        final BigDecimal expectedYearFraction = BigDecimal.valueOf(2).divide(BigDecimal.valueOf(365), MC)
                .add(BigDecimal.valueOf(2).divide(BigDecimal.valueOf(366), MC));
        final BigDecimal expected = new BigDecimal("1000.00").multiply(new BigDecimal("0.10"), MC).multiply(expectedYearFraction, MC)
                .setScale(9, RoundingMode.HALF_EVEN);

        final BigDecimal actual = period.calculateInterest(new CompoundInterestValues(BigDecimal.ZERO, BigDecimal.ZERO));

        assertEquals(expected, actual);
        assertEquals(new BigDecimal("1.09"), period.interest().getAmount());
    }

    @Test
    void shouldKeepUserPostingOnItsExplicitTransactionDateAtCurrentPeriodEnd() {
        final LocalDate startDate = LocalDate.of(2026, 1, 1);
        final LocalDate intervalEndDate = LocalDate.of(2026, 3, 30);
        final Money openingBalance = Money.of(CURRENCY, new BigDecimal("1000.00"));
        final PostingPeriod period = PostingPeriod.createFrom(LocalDateInterval.create(startDate, intervalEndDate), openingBalance,
                List.of(), CURRENCY, SavingsCompoundingInterestPeriodType.QUATERLY, SavingsInterestCalculationType.DAILY_BALANCE,
                new BigDecimal("0.03"), SavingsInterestCalculationDaysInYearType.DAYS_365, intervalEndDate, List.of(), false,
                Money.zero(CURRENCY), true, true, 1);

        assertEquals(LocalDate.of(2026, 3, 31), period.dateOfPostingTransaction());
    }

    @Test
    void shouldApplyActualToEveryNativeCompoundingPeriodAcrossYearBoundary() {
        final BigDecimal rate = new BigDecimal("0.10");
        final BigDecimal firstSegmentInterest = new BigDecimal("1000.00").multiply(rate, MC)
                .multiply(BigDecimal.valueOf(2).divide(BigDecimal.valueOf(365), MC), MC).setScale(9, RoundingMode.HALF_EVEN);
        final BigDecimal expectedPeriodic = firstSegmentInterest.add(new BigDecimal("1000.00").add(firstSegmentInterest).multiply(rate, MC)
                .multiply(BigDecimal.valueOf(2).divide(BigDecimal.valueOf(366), MC), MC).setScale(9, RoundingMode.HALF_EVEN));
        final BigDecimal factor2023 = BigDecimal.ONE.add(rate.divide(BigDecimal.valueOf(365), MC));
        final BigDecimal factor2024 = BigDecimal.ONE.add(rate.divide(BigDecimal.valueOf(366), MC));
        final BigDecimal expectedDaily = new BigDecimal("1000.00")
                .multiply(BigDecimal.valueOf(Math.pow(factor2023.doubleValue(), 2) * Math.pow(factor2024.doubleValue(), 2)), MC)
                .subtract(new BigDecimal("1000.00")).setScale(9, RoundingMode.HALF_EVEN);

        for (final SavingsCompoundingInterestPeriodType type : List.of(SavingsCompoundingInterestPeriodType.MONTHLY,
                SavingsCompoundingInterestPeriodType.QUATERLY, SavingsCompoundingInterestPeriodType.ANNUAL)) {
            final BigDecimal actual = postingPeriod(type, 1)
                    .calculateInterest(new CompoundInterestValues(BigDecimal.ZERO, BigDecimal.ZERO));
            assertEquals(expectedPeriodic, actual, type::name);
        }

        final BigDecimal actualDaily = postingPeriod(SavingsCompoundingInterestPeriodType.DAILY, 1)
                .calculateInterest(new CompoundInterestValues(BigDecimal.ZERO, BigDecimal.ZERO));
        assertEquals(expectedDaily, actualDaily);
    }

    private static EndOfDayBalance balance(final LocalDate date, final String amount, final int numberOfDays) {
        final Money money = Money.of(CURRENCY, new BigDecimal(amount));
        return EndOfDayBalance.from(date, money, money, numberOfDays);
    }

    private static PostingPeriod postingPeriod(final SavingsCompoundingInterestPeriodType compoundingType,
            final int financialYearBeginningMonth) {
        final LocalDate startDate = LocalDate.of(2023, 12, 30);
        final LocalDate endDate = LocalDate.of(2024, 1, 2);
        final Money openingBalance = Money.of(CURRENCY, new BigDecimal("1000.00"));
        return PostingPeriod.createFrom(LocalDateInterval.create(startDate, endDate), openingBalance, List.of(), CURRENCY, compoundingType,
                SavingsInterestCalculationType.DAILY_BALANCE, new BigDecimal("0.10"), SavingsInterestCalculationDaysInYearType.ACTUAL,
                endDate, List.of(), false, Money.zero(CURRENCY), true, false, financialYearBeginningMonth);
    }

    private static void assertDecimalEquals(final BigDecimal expected, final BigDecimal actual) {
        assertEquals(0, expected.compareTo(actual), () -> "expected " + expected + " but was " + actual);
    }
}
