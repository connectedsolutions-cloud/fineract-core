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
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.LocalDateInterval;
import org.apache.fineract.portfolio.savings.SavingsCompoundingInterestPeriodType;
import org.apache.fineract.portfolio.savings.SavingsInterestCalculationDaysInYearType;
import org.apache.fineract.portfolio.savings.SavingsInterestCalculationType;

public final class AnnualCompoundingPeriod implements CompoundingPeriod {

    @SuppressWarnings("unused")
    private final LocalDateInterval periodInterval;
    private final List<EndOfDayBalance> endOfDayBalances;

    public static AnnualCompoundingPeriod create(final LocalDateInterval periodInterval, final List<EndOfDayBalance> allEndOfDayBalances,
            final LocalDate upToInterestCalculationDate) {

        final List<EndOfDayBalance> endOfDayBalancesWithinPeriod = endOfDayBalancesWithinPeriodInterval(periodInterval, allEndOfDayBalances,
                upToInterestCalculationDate);

        return new AnnualCompoundingPeriod(periodInterval, endOfDayBalancesWithinPeriod);
    }

    @Override
    public BigDecimal calculateInterest(final SavingsCompoundingInterestPeriodType compoundingInterestPeriodType,
            final SavingsInterestCalculationType interestCalculationType, final BigDecimal interestToCompound,
            final BigDecimal interestRateAsFraction, final SavingsInterestCalculationDaysInYearType daysInYearType,
            final BigDecimal minBalanceForInterestCalculation, final BigDecimal overdraftInterestRateAsFraction,
            final BigDecimal minOverdraftForInterestCalculation) {

        BigDecimal interestEarned = BigDecimal.ZERO;

        switch (interestCalculationType) {
            case DAILY_BALANCE:
                interestEarned = calculateUsingDailyBalanceMethod(compoundingInterestPeriodType, interestToCompound, interestRateAsFraction,
                        daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                        minOverdraftForInterestCalculation);
            break;
            case AVERAGE_DAILY_BALANCE:
                interestEarned = calculateUsingAverageDailyBalanceMethod(interestToCompound, interestRateAsFraction, daysInYearType,
                        minBalanceForInterestCalculation, overdraftInterestRateAsFraction, minOverdraftForInterestCalculation);
            break;
            case INVALID:
            break;
        }

        return interestEarned;
    }

    private BigDecimal calculateUsingAverageDailyBalanceMethod(final BigDecimal interestToCompound, final BigDecimal interestRateAsFraction,
            final SavingsInterestCalculationDaysInYearType daysInYearType, final BigDecimal minBalanceForInterestCalculation,
            final BigDecimal overdraftInterestRateAsFraction, final BigDecimal minOverdraftForInterestCalculation) {
        return SavingsInterestDayCount.calculateAverageDailyBalanceInterest(this.endOfDayBalances, interestToCompound,
                interestRateAsFraction, daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                minOverdraftForInterestCalculation);
    }

    private BigDecimal calculateUsingDailyBalanceMethod(final SavingsCompoundingInterestPeriodType compoundingInterestPeriodType,
            final BigDecimal interestToCompound, final BigDecimal interestRateAsFraction,
            final SavingsInterestCalculationDaysInYearType daysInYearType, final BigDecimal minBalanceForInterestCalculation,
            final BigDecimal overdraftInterestRateAsFraction, final BigDecimal minOverdraftForInterestCalculation) {

        BigDecimal interestEarned = BigDecimal.ZERO;
        BigDecimal interestOnBalanceUnrounded = BigDecimal.ZERO;
        for (final EndOfDayBalance balance : this.endOfDayBalances) {

            switch (compoundingInterestPeriodType) {
                case DAILY:
                    interestOnBalanceUnrounded = balance.calculateInterestOnBalanceAndInterest(interestToCompound, interestRateAsFraction,
                            daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                            minOverdraftForInterestCalculation);
                break;
                case MONTHLY, MONTHLY_ON_ACTIVATION_DATE:
                    interestOnBalanceUnrounded = balance.calculateInterestOnBalance(interestToCompound, interestRateAsFraction,
                            daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                            minOverdraftForInterestCalculation);
                break;
                case QUATERLY:
                    interestOnBalanceUnrounded = balance.calculateInterestOnBalance(interestToCompound, interestRateAsFraction,
                            daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                            minOverdraftForInterestCalculation);
                break;
                // case WEEKLY:
                // break;
                // case BIWEEKLY:
                // break;
                case BI_ANNUAL:
                    interestOnBalanceUnrounded = balance.calculateInterestOnBalance(interestToCompound, interestRateAsFraction,
                            daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                            minOverdraftForInterestCalculation);
                break;
                case ANNUAL:
                    interestOnBalanceUnrounded = balance.calculateInterestOnBalance(interestToCompound, interestRateAsFraction,
                            daysInYearType, minBalanceForInterestCalculation, overdraftInterestRateAsFraction,
                            minOverdraftForInterestCalculation);
                break;
                // case NO_COMPOUNDING_SIMPLE_INTEREST:
                // break;
                case INVALID:
                break;
            }

            interestEarned = interestEarned.add(interestOnBalanceUnrounded);
        }
        return interestEarned;
    }

    private static List<EndOfDayBalance> endOfDayBalancesWithinPeriodInterval(final LocalDateInterval compoundingPeriodInterval,
            final List<EndOfDayBalance> allEndOfDayBalances, final LocalDate upToInterestCalculationDate) {

        final List<EndOfDayBalance> endOfDayBalancesForPeriodInterval = new ArrayList<>();

        for (final EndOfDayBalance endOfDayBalance : allEndOfDayBalances) {

            if (compoundingPeriodInterval.contains(endOfDayBalance.date())) {
                final EndOfDayBalance cappedToPeriodEndDate = endOfDayBalance.upTo(compoundingPeriodInterval, upToInterestCalculationDate);
                endOfDayBalancesForPeriodInterval.add(cappedToPeriodEndDate);
            } else if (endOfDayBalance.contains(compoundingPeriodInterval)) {
                final EndOfDayBalance cappedToPeriodEndDate = endOfDayBalance.upTo(compoundingPeriodInterval, upToInterestCalculationDate);
                endOfDayBalancesForPeriodInterval.add(cappedToPeriodEndDate);
            }
        }

        return endOfDayBalancesForPeriodInterval;
    }

    private AnnualCompoundingPeriod(final LocalDateInterval periodInterval, final List<EndOfDayBalance> endOfDayBalances) {
        this.periodInterval = periodInterval;
        this.endOfDayBalances = endOfDayBalances;
    }

    @Override
    public LocalDateInterval getPeriodInterval() {
        return this.periodInterval;
    }
}
