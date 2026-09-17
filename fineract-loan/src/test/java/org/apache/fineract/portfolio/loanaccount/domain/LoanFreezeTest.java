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

import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LoanFreezeTest {

    private final Loan loan = new Loan();

    @Test
    void freezeIsInclusiveAndUnfreezeResumesOnItsEffectiveDate() {
        LocalDate frozenOn = LocalDate.of(2026, 1, 10);
        LocalDate unfrozenOn = LocalDate.of(2026, 1, 15);

        loan.freeze(frozenOn, "Court order", "source-freeze-1");
        loan.unfreeze(unfrozenOn, "Order lifted", "source-unfreeze-1");

        assertThat(loan.isFrozenOn(frozenOn.minusDays(1))).isFalse();
        assertThat(loan.isFrozenOn(frozenOn)).isTrue();
        assertThat(loan.isFrozenOn(unfrozenOn.minusDays(1))).isTrue();
        assertThat(loan.isFrozenOn(unfrozenOn)).isFalse();
    }

    @Test
    void completedIntervalsRemainAvailableAfterASecondFreeze() {
        loan.freeze(LocalDate.of(2026, 1, 10), null, "source-freeze-1");
        loan.unfreeze(LocalDate.of(2026, 1, 15), null, "source-unfreeze-1");
        loan.freeze(LocalDate.of(2026, 2, 1), null, "source-freeze-2");

        assertThat(loan.isFrozenOn(LocalDate.of(2026, 1, 12))).isTrue();
        assertThat(loan.isFrozenOn(LocalDate.of(2026, 1, 20))).isFalse();
        assertThat(loan.isFrozenOn(LocalDate.of(2026, 2, 1))).isTrue();
        assertThat(loan.isFrozen()).isTrue();
        assertThat(loan.getFrozenOn()).isEqualTo(LocalDate.of(2026, 2, 1));
    }

    @Test
    void inconsistentFrozenCurrentStateFailsClosed() throws ReflectiveOperationException {
        var isFrozenField = Loan.class.getDeclaredField("isFrozen");
        isFrozenField.setAccessible(true);
        isFrozenField.setBoolean(loan, true);

        assertThat(loan.isFrozenOn(LocalDate.of(2026, 1, 1))).isTrue();
    }
}
