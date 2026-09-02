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

import java.time.LocalDate;
import java.time.YearMonth;
import java.time.temporal.ChronoField;
import java.time.temporal.ChronoUnit;
import java.time.temporal.Temporal;

public final class AnchoredMonthlyDateUtils {

    private AnchoredMonthlyDateUtils() {}

    public static Temporal adjustToAnchorDay(final Temporal date, final Temporal anchorDate) {
        final int lastDayOfTargetMonth = YearMonth.from(date).lengthOfMonth();
        final int anchorDay = anchorDate.get(ChronoField.DAY_OF_MONTH);
        return date.with(ChronoField.DAY_OF_MONTH, Math.min(lastDayOfTargetMonth, anchorDay));
    }

    public static LocalDate nextDateAfter(final LocalDate anchorDate, final LocalDate afterDate) {
        long monthOffset = ChronoUnit.MONTHS.between(YearMonth.from(anchorDate), YearMonth.from(afterDate));
        LocalDate candidate = (LocalDate) adjustToAnchorDay(anchorDate.plusMonths(monthOffset), anchorDate);
        if (!candidate.isAfter(afterDate)) {
            candidate = (LocalDate) adjustToAnchorDay(anchorDate.plusMonths(++monthOffset), anchorDate);
        }
        return candidate;
    }
}
