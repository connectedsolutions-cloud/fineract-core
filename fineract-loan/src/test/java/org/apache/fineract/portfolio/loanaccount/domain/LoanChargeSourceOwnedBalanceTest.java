/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software distributed under the License is
 * distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import org.apache.fineract.portfolio.charge.domain.ChargeCalculationType;
import org.apache.fineract.portfolio.charge.domain.ChargeTimeType;
import org.junit.jupiter.api.Test;

class LoanChargeSourceOwnedBalanceTest {

    @Test
    void rebasePreservesRecordedPaymentWhileReplacingOutstanding() {
        LoanCharge charge = cutoverCharge();
        charge.setAmount(new BigDecimal("1.26"));
        charge.setAmountPaid(new BigDecimal("0.72"));
        charge.setAmountOutstanding(new BigDecimal("0.54"));

        charge.rebaseSourceOwnedOutstanding(new BigDecimal("1.53"));

        assertEquals(0, charge.getAmountPaid().compareTo(new BigDecimal("0.72")));
        assertEquals(0, charge.getAmount().compareTo(new BigDecimal("2.25")));
        assertEquals(0, charge.getAmountOrPercentage().compareTo(new BigDecimal("2.25")));
        assertEquals(0, charge.amountOutstanding().compareTo(new BigDecimal("1.53")));
        assertEquals(0, charge.calculateOutstanding().compareTo(new BigDecimal("1.53")));
        charge.rebaseSourceOwnedOutstanding(new BigDecimal("1.53"));
        assertEquals(0, charge.getAmount().compareTo(new BigDecimal("2.25")));
    }

    @Test
    void rebaseCanReduceOutstandingToZeroWithoutDiscardingPayment() {
        LoanCharge charge = cutoverCharge();
        charge.setAmountPaid(new BigDecimal("0.72"));
        charge.setAmountOutstanding(new BigDecimal("0.54"));

        charge.rebaseSourceOwnedOutstanding(BigDecimal.ZERO);

        assertEquals(0, charge.getAmount().compareTo(new BigDecimal("0.72")));
        assertEquals(0, charge.amountOutstanding().compareTo(BigDecimal.ZERO));
        assertEquals(true, charge.isPaid());
    }

    @Test
    void rebaseRejectsNegativeSourceBalance() {
        LoanCharge charge = cutoverCharge();
        assertThrows(IllegalArgumentException.class, () -> charge.rebaseSourceOwnedOutstanding(new BigDecimal("-0.01")));
    }

    private static LoanCharge cutoverCharge() {
        LoanCharge charge = new LoanCharge();
        charge.setChargeTime(ChargeTimeType.SPECIFIED_DUE_DATE.getValue());
        charge.setChargeCalculation(ChargeCalculationType.FLAT.getValue());
        return charge;
    }
}
