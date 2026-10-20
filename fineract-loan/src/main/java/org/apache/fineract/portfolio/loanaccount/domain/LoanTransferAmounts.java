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

import java.math.BigDecimal;

/** The dated source balance posted by both sides of a source-exact loan office transfer. */
public record LoanTransferAmounts(BigDecimal amount, BigDecimal principal, BigDecimal interest, BigDecimal fee, BigDecimal penalty) {

    public LoanTransferAmounts {
        if (amount == null || principal == null || interest == null || fee == null || penalty == null || amount.signum() <= 0
                || principal.signum() < 0 || interest.signum() < 0 || fee.signum() < 0 || penalty.signum() < 0
                || principal.add(interest).add(fee).add(penalty).compareTo(amount) != 0) {
            throw new IllegalArgumentException("Invalid source-exact loan transfer balance components");
        }
    }
}
