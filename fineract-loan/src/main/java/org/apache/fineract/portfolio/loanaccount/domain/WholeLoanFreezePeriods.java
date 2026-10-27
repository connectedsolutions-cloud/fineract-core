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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Whole-loan freeze begins inclusively; unfreeze is the first chargeable day. */
public final class WholeLoanFreezePeriods {

    private WholeLoanFreezePeriods() {}

    public static List<CredesalInterestPausePeriods.Period> fromLoan(Loan loan, LocalDate through) {
        List<CredesalInterestPausePeriods.Period> result = new ArrayList<>();
        LocalDate start = null;
        for (var event : loan.getFreezeHistory().stream().sorted(Comparator.comparing(LoanFreezeHistory::getEffectiveDate)
                .thenComparing(e -> e.getId() == null ? Long.MAX_VALUE : e.getId())).toList()) {
            if (event.getEffectiveDate().isAfter(through)) break;
            if (event.getAction() == LoanFreezeAction.FREEZE) start = event.getEffectiveDate();
            if (event.getAction() == LoanFreezeAction.UNFREEZE && start != null) {
                if (start.isBefore(event.getEffectiveDate()))
                    result.add(new CredesalInterestPausePeriods.Period(start, event.getEffectiveDate().minusDays(1)));
                start = null;
            }
        }
        if (start != null) result.add(new CredesalInterestPausePeriods.Period(start, through));
        if (result.isEmpty() && loan.isFrozen() && loan.getFrozenOn() != null && !loan.getFrozenOn().isAfter(through))
            result.add(new CredesalInterestPausePeriods.Period(loan.getFrozenOn(), through));
        return result;
    }
}
