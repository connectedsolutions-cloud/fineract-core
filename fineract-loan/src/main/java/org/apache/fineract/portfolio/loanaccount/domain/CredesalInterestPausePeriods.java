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

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import org.apache.fineract.portfolio.loanaccount.data.LoanTermVariationsData;

/** Date arithmetic shared by the Credesal cumulative schedule and post-due interest calculations. */
public final class CredesalInterestPausePeriods {

    public record Period(LocalDate startDate, LocalDate endDate) {
    }

    private CredesalInterestPausePeriods() {}

    public static List<Period> fromLoan(final Loan loan) {
        if (loan.getLoanTermVariations() == null) {
            return List.of();
        }
        return loan.getLoanTermVariations().stream()
                .filter(variation -> Boolean.TRUE.equals(variation.isActive()) && variation.getTermType().isInterestPauseVariation())
                .map(variation -> new Period(variation.getTermApplicableFrom(), variation.getDateValue())).toList();
    }

    public static List<Period> fromData(final Collection<LoanTermVariationsData> variations) {
        return variations.stream().filter(variation -> variation.getTermVariationType().isInterestPauseVariation())
                .map(variation -> new Period(variation.getTermVariationApplicableFrom(), variation.getDateValue())).toList();
    }

    /** Counts chargeable days in (fromDate, throughDate], with pause bounds inclusive. */
    public static long chargeableDays(final LocalDate fromDate, final LocalDate throughDate, final Collection<Period> pauses) {
        if (!fromDate.isBefore(throughDate)) {
            return 0;
        }
        long days = ChronoUnit.DAYS.between(fromDate, throughDate);
        LocalDate previousPausedEnd = fromDate;
        for (Period pause : pauses.stream().sorted((left, right) -> left.startDate().compareTo(right.startDate())).toList()) {
            LocalDate firstPausedDay = pause.startDate().isAfter(fromDate) ? pause.startDate() : fromDate.plusDays(1);
            if (!firstPausedDay.isAfter(previousPausedEnd)) {
                firstPausedDay = previousPausedEnd.plusDays(1);
            }
            LocalDate lastPausedDay = pause.endDate().isBefore(throughDate) ? pause.endDate() : throughDate;
            if (!firstPausedDay.isAfter(lastPausedDay)) {
                days -= ChronoUnit.DAYS.between(firstPausedDay, lastPausedDay) + 1;
                previousPausedEnd = lastPausedDay;
            }
        }
        return days;
    }
}
