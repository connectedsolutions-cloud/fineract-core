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
package org.apache.fineract.portfolio.loanaccount.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;

class CredesalDailyMoraCalculatorTest {

    private final CredesalDailyMoraCalculator calculator = new CredesalDailyMoraCalculator();

    @Test
    void reproducesArisstoLoan1807October19Close() {
        final List<CredesalDailyMoraCalculator.Installment> schedule = List.of(
                installment("2026-09-10", "93.17", "64.55"), installment("2026-09-25", "64.55", "32.82"),
                installment("2026-10-10", "32.82", "0.00"));
        assertEquals(new BigDecimal("0.31"), calculator.calculate(LocalDate.parse("2026-10-19"),
                new BigDecimal("93.17"), new BigDecimal("93.17"), 25, 0, null, new BigDecimal("0.42"), schedule, 2));
        final BigDecimal prior = calculator.calculate(LocalDate.parse("2026-10-18"),
                new BigDecimal("93.17"), new BigDecimal("93.17"), 24, 0, null, new BigDecimal("0.42"), schedule, 2);
        assertEquals(new BigDecimal("0.29"), prior);
        assertEquals(new BigDecimal("0.02"), new BigDecimal("0.31").subtract(prior));
    }

    @Test
    void accruesCumulativelyAndRoundsEachInstallmentOnlyAtTheEnd() {
        final var schedule = List.of(installment("2026-09-10", "28.62", "0.00"));
        assertEquals(new BigDecimal("0.16"), calculator.calculate(LocalDate.parse("2026-10-19"),
                new BigDecimal("28.62"), new BigDecimal("28.62"), 39, 0, null, new BigDecimal("0.42"), schedule, 2));
    }

    @Test
    void lastMoraPaymentResetsTheDaysAndGraceOrNoOverduePrincipalDisablesMora() {
        final var schedule = List.of(installment("2026-09-10", "100.00", "0.00"));
        final LocalDate operationDate = LocalDate.parse("2026-10-10");
        assertEquals(new BigDecimal("0.07"), calculator.calculate(operationDate, new BigDecimal("100.00"),
                new BigDecimal("100.00"), 30, 0, LocalDate.parse("2026-10-05"), new BigDecimal("0.42"), schedule, 2));
        assertEquals(new BigDecimal("0.00"), calculator.calculate(operationDate, new BigDecimal("100.00"),
                new BigDecimal("100.00"), 5, 5, null, new BigDecimal("0.42"), schedule, 2));
        assertEquals(new BigDecimal("0.00"), calculator.calculate(operationDate, new BigDecimal("100.00"),
                BigDecimal.ZERO, 30, 0, null, new BigDecimal("0.42"), schedule, 2));
    }

    private static CredesalDailyMoraCalculator.Installment installment(final String date, final String before,
            final String after) {
        return new CredesalDailyMoraCalculator.Installment(LocalDate.parse(date), new BigDecimal(before), new BigDecimal(after));
    }
}
