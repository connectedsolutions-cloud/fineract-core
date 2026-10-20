/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.organisation.teller.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class CashierCashAuditServiceImplTest {

    @Test
    void onlyKnownCashPaymentsHavePhysicalCashDirection() {
        assertThat(CashierCashAuditServiceImpl.classifyProduct("LOAN", "REPAYMENT", true, true, false)).isEqualTo("CASH_IN");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("LOAN", "DISBURSEMENT", true, true, false))
                .isEqualTo("UNVERIFIED");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("SAVINGS", "deposit", true, true, false)).isEqualTo("CASH_IN");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("SAVINGS", "withdrawal", true, true, false)).isEqualTo("CASH_OUT");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("CLIENT", "PAY_CHARGE", true, true, false)).isEqualTo("CASH_IN");
    }

    @Test
    void unknownPaymentMethodAndNonCashEventsDoNotIncreaseExpectedCash() {
        assertThat(CashierCashAuditServiceImpl.classifyProduct("LOAN", "REPAYMENT", false, null, false)).isEqualTo("UNVERIFIED");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("LOAN", "REPAYMENT", true, false, false)).isEqualTo("NON_CASH");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("SAVINGS", "Interest Posting", true, true, false))
                .isEqualTo("UNVERIFIED");
        assertThat(CashierCashAuditServiceImpl.classifyProduct("LOAN", "REPAYMENT", true, true, true)).isEqualTo("REVERSED");
    }
}
