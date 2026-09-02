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

import java.math.BigDecimal;
import java.math.MathContext;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.List;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.savings.SavingsInterestCalculationDaysInYearType;

public final class SavingsInterestDayCount {

    private SavingsInterestDayCount() {}

    public static BigDecimal yearFraction(final LocalDate startDate, final int numberOfDays,
            final SavingsInterestCalculationDaysInYearType type) {
        if (numberOfDays <= 0) {
            return BigDecimal.ZERO;
        }
        if (!type.isActual()) {
            return BigDecimal.valueOf(numberOfDays).divide(BigDecimal.valueOf(type.getValue()), MathContext.DECIMAL64);
        }

        BigDecimal fraction = BigDecimal.ZERO;
        LocalDate segmentStart = startDate;
        final LocalDate endExclusive = startDate.plusDays(numberOfDays);
        while (segmentStart.isBefore(endExclusive)) {
            final LocalDate nextYear = LocalDate.of(segmentStart.getYear() + 1, 1, 1);
            final LocalDate segmentEnd = nextYear.isBefore(endExclusive) ? nextYear : endExclusive;
            final long segmentDays = ChronoUnit.DAYS.between(segmentStart, segmentEnd);
            fraction = fraction
                    .add(BigDecimal.valueOf(segmentDays).divide(BigDecimal.valueOf(segmentStart.lengthOfYear()), MathContext.DECIMAL64));
            segmentStart = segmentEnd;
        }
        return fraction;
    }

    public static BigDecimal dailyCompoundingFactor(final BigDecimal annualRate, final LocalDate startDate, final int numberOfDays,
            final SavingsInterestCalculationDaysInYearType type) {
        if (numberOfDays <= 0) {
            return BigDecimal.ONE;
        }
        if (!type.isActual()) {
            final BigDecimal multiplicand = BigDecimal.ONE.divide(BigDecimal.valueOf(type.getValue()), MathContext.DECIMAL64);
            final BigDecimal dailyRate = annualRate.multiply(multiplicand);
            return BigDecimal.valueOf(Math.pow(BigDecimal.ONE.add(dailyRate).doubleValue(), numberOfDays));
        }

        double factor = 1.0;
        LocalDate segmentStart = startDate;
        final LocalDate endExclusive = startDate.plusDays(numberOfDays);
        while (segmentStart.isBefore(endExclusive)) {
            final LocalDate nextYear = LocalDate.of(segmentStart.getYear() + 1, 1, 1);
            final LocalDate segmentEnd = nextYear.isBefore(endExclusive) ? nextYear : endExclusive;
            final long segmentDays = ChronoUnit.DAYS.between(segmentStart, segmentEnd);
            final BigDecimal dailyRate = annualRate.divide(BigDecimal.valueOf(segmentStart.lengthOfYear()), MathContext.DECIMAL64);
            factor *= Math.pow(BigDecimal.ONE.add(dailyRate).doubleValue(), segmentDays);
            segmentStart = segmentEnd;
        }
        return BigDecimal.valueOf(factor);
    }

    public static BigDecimal calculateAverageDailyBalanceInterest(final List<EndOfDayBalance> balances, final BigDecimal interestToCompound,
            final BigDecimal interestRateAsFraction, final SavingsInterestCalculationDaysInYearType type,
            final BigDecimal minBalanceForInterestCalculation, final BigDecimal overdraftInterestRateAsFraction,
            final BigDecimal minOverdraftForInterestCalculation) {
        BigDecimal cumulativeBalance = BigDecimal.ZERO;
        BigDecimal annualizedCumulativeBalance = BigDecimal.ZERO;
        int numberOfDays = 0;
        for (final EndOfDayBalance balance : balances) {
            cumulativeBalance = cumulativeBalance.add(balance.cumulativeBalance(interestToCompound));
            annualizedCumulativeBalance = annualizedCumulativeBalance.add(balance.annualizedCumulativeBalance(interestToCompound, type));
            numberOfDays += balance.getNumberOfDays();
        }

        if (cumulativeBalance.compareTo(BigDecimal.ZERO) == 0 || numberOfDays == 0) {
            return BigDecimal.ZERO;
        }

        final BigDecimal averageDailyBalance = cumulativeBalance.divide(BigDecimal.valueOf(numberOfDays), MathContext.DECIMAL64).setScale(9,
                MoneyHelper.getRoundingMode());
        BigDecimal applicableRate = null;
        if (averageDailyBalance.compareTo(BigDecimal.ZERO) >= 0 && averageDailyBalance.compareTo(minBalanceForInterestCalculation) >= 0) {
            applicableRate = interestRateAsFraction;
        } else if (averageDailyBalance.compareTo(minOverdraftForInterestCalculation.negate()) < 0) {
            applicableRate = overdraftInterestRateAsFraction;
        }

        if (applicableRate == null) {
            return BigDecimal.ZERO;
        }
        if (type.isActual()) {
            return annualizedCumulativeBalance.multiply(applicableRate, MathContext.DECIMAL64).setScale(9, MoneyHelper.getRoundingMode());
        }

        final BigDecimal multiplicand = BigDecimal.ONE.divide(BigDecimal.valueOf(type.getValue()), MathContext.DECIMAL64);
        final BigDecimal dailyInterestRate = applicableRate.multiply(multiplicand, MathContext.DECIMAL64);
        final BigDecimal periodicInterestRate = dailyInterestRate.multiply(BigDecimal.valueOf(numberOfDays), MathContext.DECIMAL64);
        return averageDailyBalance.multiply(periodicInterestRate, MathContext.DECIMAL64).setScale(9, MoneyHelper.getRoundingMode());
    }
}
