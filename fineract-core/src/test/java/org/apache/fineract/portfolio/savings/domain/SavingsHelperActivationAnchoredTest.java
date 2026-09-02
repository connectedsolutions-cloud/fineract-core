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
package org.apache.fineract.portfolio.savings.domain;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.LocalDateInterval;
import org.apache.fineract.portfolio.savings.SavingsCompoundingInterestPeriodType;
import org.apache.fineract.portfolio.savings.SavingsPostingInterestPeriodType;
import org.apache.fineract.portfolio.savings.service.SavingsEnumerations;
import org.junit.jupiter.api.Test;

class SavingsHelperActivationAnchoredTest {

    private final SavingsHelper savingsHelper = new SavingsHelper(null);

    @Test
    void shouldBuildPostingPeriodsFromTheImmutableActivationDate() {
        final List<LocalDateInterval> periods = savingsHelper.determineInterestPostingPeriods(LocalDate.of(2023, 1, 31),
                LocalDate.of(2023, 1, 31), LocalDate.of(2023, 4, 29), SavingsPostingInterestPeriodType.MONTHLY_ON_ACTIVATION_DATE, 1,
                new ArrayList<>());

        assertThat(periods).hasSize(3);
        assertThat(periods.stream().map(period -> period.endDate().plusDays(1)).toList()).containsExactly(LocalDate.of(2023, 2, 28),
                LocalDate.of(2023, 3, 31), LocalDate.of(2023, 4, 30));
    }

    @Test
    void shouldRetainActivationAnchorWhenCalculationStartsMidCycle() {
        final List<LocalDateInterval> periods = savingsHelper.determineInterestPostingPeriods(LocalDate.of(2024, 2, 15),
                LocalDate.of(2024, 1, 31), LocalDate.of(2024, 2, 28), SavingsPostingInterestPeriodType.MONTHLY_ON_ACTIVATION_DATE, 1,
                new ArrayList<>());

        assertThat(periods.getFirst().startDate()).isEqualTo(LocalDate.of(2024, 2, 15));
        assertThat(periods.getFirst().endDate().plusDays(1)).isEqualTo(LocalDate.of(2024, 2, 29));
    }

    @Test
    void shouldExposeStablePostingAndCompoundingEnumIdentities() {
        assertThat(SavingsPostingInterestPeriodType.fromInt(9)).isEqualTo(SavingsPostingInterestPeriodType.MONTHLY_ON_ACTIVATION_DATE);
        assertThat(SavingsCompoundingInterestPeriodType.fromInt(9))
                .isEqualTo(SavingsCompoundingInterestPeriodType.MONTHLY_ON_ACTIVATION_DATE);
        assertThat(SavingsEnumerations.interestPostingPeriodType(9).getId()).isEqualTo(9L);
        assertThat(SavingsEnumerations.compoundingInterestPeriodType(9).getId()).isEqualTo(9L);
    }
}
