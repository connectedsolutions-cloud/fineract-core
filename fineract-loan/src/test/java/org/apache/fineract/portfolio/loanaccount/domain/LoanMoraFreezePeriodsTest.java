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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;

class LoanMoraFreezePeriodsTest {
    private final Loan loan = new Loan();
    private static LocalDate date(String value) { return LocalDate.parse(value); }
    private void event(LoanFreezeAction action, String value) {
        loan.getFreezeHistory().add(new LoanFreezeHistory(loan, action, date(value), null, null));
    }

    @Test
    void moraControlsDoNotChangeWholeLoanFreezeAndResumeIsInclusive() {
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-05");
        event(LoanFreezeAction.MORA_UNFREEZE, "2026-10-10");
        assertThat(loan.isFrozenOn(date("2026-10-07"))).isFalse();
        assertThat(LoanMoraFreezePeriods.isMoraFrozen(loan.getFreezeHistory(), date("2026-10-04"))).isFalse();
        assertThat(LoanMoraFreezePeriods.isMoraFrozen(loan.getFreezeHistory(), date("2026-10-05"))).isTrue();
        assertThat(LoanMoraFreezePeriods.isMoraFrozen(loan.getFreezeHistory(), date("2026-10-09"))).isTrue();
        assertThat(LoanMoraFreezePeriods.isMoraFrozen(loan.getFreezeHistory(), date("2026-10-10"))).isFalse();
    }

    @Test
    void wholeLoanAndMoraFreezeOverlapIsCountedOnlyOnce() {
        loan.freeze(date("2026-10-03"), null, null);
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-05");
        loan.unfreeze(date("2026-10-08"), null, null);
        event(LoanFreezeAction.MORA_UNFREEZE, "2026-10-10");
        final var periods = LoanMoraFreezePeriods.fromLoan(loan, date("2026-10-11"));
        assertThat(CredesalInterestPausePeriods.chargeableDays(date("2026-10-01"), date("2026-10-11"), periods)).isEqualTo(3);
        assertThat(loan.isFrozenOn(date("2026-10-06"))).isTrue();
        assertThat(loan.isFrozenOn(date("2026-10-08"))).isFalse();
    }

    @Test
    void cumulativeMoraNeverCatchesUpCompletedIntervalsAndClipsToPaymentDate() {
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-05");
        event(LoanFreezeAction.MORA_UNFREEZE, "2026-10-10");
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-12");
        event(LoanFreezeAction.MORA_UNFREEZE, "2026-10-14");
        final var calculator = new CredesalDailyMoraCalculator();
        final var schedule = List.of(new CredesalDailyMoraCalculator.Installment(date("2026-10-01"), new BigDecimal("1000"), BigDecimal.ZERO));
        final var periods = LoanMoraFreezePeriods.fromLoan(loan, date("2026-10-15"));
        assertThat(calculator.calculate(date("2026-10-15"), new BigDecimal("1000"), new BigDecimal("1000"), 14,
                0, null, new BigDecimal("3"), schedule, 2, periods)).isEqualByComparingTo("7.00");
        assertThat(calculator.calculate(date("2026-10-15"), new BigDecimal("1000"), new BigDecimal("1000"), 14,
                0, date("2026-10-07"), new BigDecimal("3"), schedule, 2, periods)).isEqualByComparingTo("4.00");
    }

    @Test
    void sameDayFreezeAndUnfreezeExcludeNoDaysAndOpenFreezeIsClipped() {
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-05");
        event(LoanFreezeAction.MORA_UNFREEZE, "2026-10-05");
        assertThat(LoanMoraFreezePeriods.fromLoan(loan, date("2026-10-10"))).isEmpty();
        event(LoanFreezeAction.MORA_FREEZE, "2026-10-08");
        assertThat(CredesalInterestPausePeriods.chargeableDays(date("2026-10-01"), date("2026-10-10"),
                LoanMoraFreezePeriods.fromLoan(loan, date("2026-10-10")))).isEqualTo(6);
    }
}
