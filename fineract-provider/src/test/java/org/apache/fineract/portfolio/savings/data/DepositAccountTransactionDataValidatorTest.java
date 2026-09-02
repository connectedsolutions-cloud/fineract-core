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

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;

import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.junit.jupiter.api.Test;

class DepositAccountTransactionDataValidatorTest {

    @Test
    void shouldAllowSourceAuthoritativeFixedDepositClosureWithoutMaturityInterestRecalculation() {
        final FromJsonHelper json = new FromJsonHelper();
        final String request = """
                {
                  "closedOnDate": "18 May 2026",
                  "dateFormat": "dd MMMM yyyy",
                  "locale": "en",
                  "onAccountClosureId": 100,
                  "paymentTypeId": 4,
                  "postMaturityInterest": false
                }
                """;
        final JsonCommand command = JsonCommand.from(request, json.parse(request), json, null, 1L, null, null, null, null, null, null,
                null, null, null, null, null, null);

        assertDoesNotThrow(() -> new DepositAccountTransactionDataValidator(json).validateClosing(
                command, DepositAccountType.FIXED_DEPOSIT, false));
    }
}
