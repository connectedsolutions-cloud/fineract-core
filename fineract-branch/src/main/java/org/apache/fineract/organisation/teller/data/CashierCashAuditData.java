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
package org.apache.fineract.organisation.teller.data;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/** Read-only evidence for a cashier's physical-cash expectation. Not a close authorization. */
public record CashierCashAuditData(Long tellerId, Long cashierId, String currencyCode, Instant asOf, BigDecimal openingCash,
        BigDecimal allocations, BigDecimal cashReceipts, BigDecimal cashPayouts, BigDecimal settlements, BigDecimal expectedCash, BigDecimal legacyExpectedCash,
        int unverifiedEvents, int unattributedCandidates, List<Event> events) {

    public record Event(String source, Long sourceId, LocalDate businessDate, String operation, String classification, BigDecimal amount,
            boolean reversed, Long cashierId) {
    }
}
