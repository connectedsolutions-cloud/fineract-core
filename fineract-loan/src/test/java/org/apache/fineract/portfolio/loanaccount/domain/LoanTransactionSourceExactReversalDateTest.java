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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.LocalDate;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.junit.jupiter.api.Test;

class LoanTransactionSourceExactReversalDateTest {

    @Test
    void storesSourceEffectiveDateWithoutChangingOriginalPaymentDate() {
        LocalDate paymentDate = LocalDate.of(2026, 9, 9);
        LocalDate reversalDate = LocalDate.of(2026, 9, 17);
        LoanTransaction payment = new LoanTransaction();
        payment.updateTransactionDate(paymentDate);
        ExternalId reversalId = ExternalId.generate();

        payment.reverse(reversalId, reversalDate);

        assertTrue(payment.isReversed());
        assertEquals(paymentDate, payment.getTransactionDate());
        assertEquals(reversalDate, payment.getReversedOnDate());
        assertEquals(reversalId, payment.getReversalExternalId());
        assertThrows(IllegalArgumentException.class, () -> payment.reverse(reversalId, paymentDate.minusDays(1)));
    }
}
