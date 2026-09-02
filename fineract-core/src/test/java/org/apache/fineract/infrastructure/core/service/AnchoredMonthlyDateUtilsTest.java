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
package org.apache.fineract.infrastructure.core.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class AnchoredMonthlyDateUtilsTest {

    @Test
    void shouldRestoreTheOriginalDayAfterAShortMonth() {
        final LocalDate anchor = LocalDate.of(2023, 1, 31);

        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, anchor)).isEqualTo(LocalDate.of(2023, 2, 28));
        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, LocalDate.of(2023, 2, 28))).isEqualTo(LocalDate.of(2023, 3, 31));
        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, LocalDate.of(2023, 3, 31))).isEqualTo(LocalDate.of(2023, 4, 30));
        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, LocalDate.of(2023, 4, 30))).isEqualTo(LocalDate.of(2023, 5, 31));
    }

    @Test
    void shouldUseLeapDayAndKeepTheImmutableAnchorDuringRecalculation() {
        final LocalDate anchor = LocalDate.of(2024, 1, 31);

        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, LocalDate.of(2024, 2, 15))).isEqualTo(LocalDate.of(2024, 2, 29));
        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(anchor, LocalDate.of(2024, 2, 29))).isEqualTo(LocalDate.of(2024, 3, 31));
    }

    @Test
    void shouldPreserveTheLoanSeedAcrossAThirtyDayMonth() {
        final LocalDate loanSeed = LocalDate.of(2024, 5, 31);

        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(loanSeed, loanSeed)).isEqualTo(LocalDate.of(2024, 6, 30));
        assertThat(AnchoredMonthlyDateUtils.nextDateAfter(loanSeed, LocalDate.of(2024, 6, 30))).isEqualTo(LocalDate.of(2024, 7, 31));
    }
}
