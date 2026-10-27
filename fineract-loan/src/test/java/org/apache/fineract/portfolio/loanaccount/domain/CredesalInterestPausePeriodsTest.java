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

import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;

class CredesalInterestPausePeriodsTest {

    @Test
    void pauseBoundsAreInclusiveAndInterestResumesTheFollowingDay() {
        final LocalDate dueDate = LocalDate.of(2026, 6, 28);
        final var pauses = List.of(new CredesalInterestPausePeriods.Period(dueDate.plusDays(1), dueDate.plusDays(2)));

        assertEquals(0, CredesalInterestPausePeriods.chargeableDays(dueDate, dueDate.plusDays(2), pauses));
        assertEquals(2, CredesalInterestPausePeriods.chargeableDays(dueDate, dueDate.plusDays(4), pauses));
    }

    @Test
    void overlappingPausesNeverRemoveTheSameDayTwice() {
        final LocalDate start = LocalDate.of(2026, 6, 1);
        final var pauses = List.of(new CredesalInterestPausePeriods.Period(start.plusDays(2), start.plusDays(4)),
                new CredesalInterestPausePeriods.Period(start.plusDays(4), start.plusDays(6)));

        assertEquals(2, CredesalInterestPausePeriods.chargeableDays(start, start.plusDays(7), pauses));
    }
}
