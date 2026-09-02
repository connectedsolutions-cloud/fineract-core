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
package org.apache.fineract.portfolio.savings.data;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;
import org.apache.fineract.organisation.monetary.data.CurrencyData;
import org.apache.fineract.portfolio.savings.SavingsAccountTransactionType;
import org.junit.jupiter.api.Test;

class SavingsAccountTransactionDataTest {

    @Test
    void shouldPreserveReferencedManualInterestIdentityForScheduledPosting() {
        final SavingsAccountTransactionEnumData type = new SavingsAccountTransactionEnumData(
                SavingsAccountTransactionType.INTEREST_POSTING.getValue().longValue(),
                SavingsAccountTransactionType.INTEREST_POSTING.getCode(), null);
        final CurrencyData currency = new CurrencyData("USD", "US Dollar", 2, 1, "$", "currency.USD");

        final SavingsAccountTransactionData transaction = SavingsAccountTransactionData.createForInterestPosting(1L, type, null, 2L, "0002",
                LocalDate.of(2026, 8, 1), currency, new BigDecimal("4.17"), null, new BigDecimal("104.17"), false, LocalDate.of(2026, 8, 1),
                false, new BigDecimal("104.17"), LocalDate.of(2026, 8, 1), true, "AHO_MOVIMIENTOS|1102");

        assertThat(transaction.isManualTransaction()).isTrue();
        assertThat(transaction.getRefNo()).isEqualTo("AHO_MOVIMIENTOS|1102");
        assertThat(transaction.isReferencedManualInterestPosting()).isTrue();
    }
}
