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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import java.util.Objects;
import java.util.function.Supplier;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;

/** Only the authenticated source-exact terminal-adjustment command enters this scope. */
public final class SourceExactTerminalAdjustmentContext {
    private static final ThreadLocal<Boolean> ACTIVE = ThreadLocal.withInitial(() -> false);
    private SourceExactTerminalAdjustmentContext() {}

    public static boolean isActive() { return ACTIVE.get(); }

    public static boolean isArisstoLoan(Loan loan) {
        String id = loan.getExternalId() == null ? null : loan.getExternalId().getValue();
        return id != null && id.matches("(?:PROOF:[a-z0-9][a-z0-9-]{0,23}:)?ARISSTO:CRD:[0-9]+");
    }

    public static boolean preservesExpectedDates(Loan loan) {
        return isActive() && isArisstoLoan(loan) && !loan.isInterestRecalculationEnabled()
                && loan.getPortfolioAccountGlId() != null
                && Objects.equals(loan.getExpectedDisbursementDate(), loan.getPortfolioAccountExpectedDisbursementDate())
                && Objects.equals(loan.getExpectedMaturityDate(), loan.getPortfolioAccountExpectedMaturityDate());
    }

    public static <T> T execute(Supplier<T> action) {
        boolean previous = ACTIVE.get();
        ACTIVE.set(true);
        try { return action.get(); }
        finally {
            if (previous) ACTIVE.set(true);
            else ACTIVE.remove();
        }
    }
}
