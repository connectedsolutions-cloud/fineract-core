/**
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.domain;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Mora-only controls coexist with whole-loan freezes; both exclude mora days. */
public final class LoanMoraFreezePeriods {
    private LoanMoraFreezePeriods() {}

    public static List<CredesalInterestPausePeriods.Period> fromLoan(final Loan loan, final LocalDate throughDate) {
        final List<CredesalInterestPausePeriods.Period> periods = new ArrayList<>();
        periods.addAll(periods(loan.getFreezeHistory(), LoanFreezeAction.MORA_FREEZE, LoanFreezeAction.MORA_UNFREEZE, throughDate));
        periods.addAll(periods(loan.getFreezeHistory(), LoanFreezeAction.FREEZE, LoanFreezeAction.UNFREEZE, throughDate));
        // Preserve legacy whole-loan current state even when no history has been recorded.
        if (loan.isFrozen() && loan.getFrozenOn() != null && loan.getFreezeHistory().stream()
                .noneMatch(event -> event.getAction() == LoanFreezeAction.FREEZE)) {
            periods.add(new CredesalInterestPausePeriods.Period(loan.getFrozenOn(), throughDate));
        }
        return periods;
    }

    public static boolean isMoraFrozen(final List<LoanFreezeHistory> history, final LocalDate date) {
        return periods(history, LoanFreezeAction.MORA_FREEZE, LoanFreezeAction.MORA_UNFREEZE, date).stream()
                .anyMatch(period -> !date.isBefore(period.startDate()) && !date.isAfter(period.endDate()));
    }

    private static List<CredesalInterestPausePeriods.Period> periods(final List<LoanFreezeHistory> history,
            final LoanFreezeAction freeze, final LoanFreezeAction unfreeze, final LocalDate throughDate) {
        final List<CredesalInterestPausePeriods.Period> result = new ArrayList<>();
        LocalDate start = null;
        for (LoanFreezeHistory event : history.stream().sorted(Comparator.comparing(LoanFreezeHistory::getEffectiveDate)).toList()) {
            if (event.getEffectiveDate().isAfter(throughDate)) {
                break;
            }
            if (event.getAction() == freeze) {
                start = event.getEffectiveDate();
            } else if (event.getAction() == unfreeze && start != null) {
                if (start.isBefore(event.getEffectiveDate())) {
                    result.add(new CredesalInterestPausePeriods.Period(start, event.getEffectiveDate().minusDays(1)));
                }
                start = null;
            }
        }
        if (start != null) {
            result.add(new CredesalInterestPausePeriods.Period(start, throughDate));
        }
        return result;
    }
}
