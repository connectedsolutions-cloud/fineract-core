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
package org.apache.fineract.accounting.journalentry.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.organisation.office.domain.Office;
import org.junit.jupiter.api.Test;

class RefinancingJournalAssemblerTest {

    @org.junit.jupiter.api.BeforeEach
    void setup() {
        org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil.setBusinessDates(new java.util.HashMap<>(
                java.util.Map.of(org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType.BUSINESS_DATE, date)));
    }

    @org.junit.jupiter.api.AfterEach
    void cleanup() {
        org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil.reset();
    }

    private final LocalDate date = LocalDate.of(2026, 10, 30);
    private final GLAccount portfolio = account(1L);
    private final GLAccount cash = account(2L);
    private final GLAccount interest = account(3L);
    private final GLAccount payable = account(4L);
    private final GLAccount fees = account(5L);
    private final GLAccount savings = account(6L);
    private final Office office = mock(Office.class);
    private final Office predecessorOffice = mock(Office.class);

    private GLAccount account(Long id) {
        GLAccount a = mock(GLAccount.class);
        when(a.getId()).thenReturn(id);
        return a;
    }

    private void entry(long loan, long tx, int type, GLAccount account, boolean debit, String amount) {
        RefinancingJournalContext.register(loan, tx, type, date, true);
        JournalEntry e = JournalEntry.createNew(loan == 9 ? predecessorOffice : office, null, account, "USD", "L" + tx, false, date,
                debit ? JournalEntryType.DEBIT : JournalEntryType.CREDIT, new BigDecimal(amount), "test", 1, loan, null, tx, null, null,
                null, null);
        assertTrue(RefinancingJournalContext.capture(e));
    }

    private void oldPayoff() {
        entry(10, 1, 1, portfolio, true, "161.01");
        entry(10, 1, 1, cash, false, "161.01");
        entry(9, 2, 2, cash, true, "161.01");
        entry(9, 2, 2, portfolio, false, "158.83");
        entry(9, 2, 2, interest, false, "2.18");
    }

    private List<JournalEntry> assemble(RefinancingJournalContext c, String amount) {
        return RefinancingJournalAssembler.assemble(c, 10L, new BigDecimal("400"), 1L, Set.of(2L), payable, new BigDecimal(amount));
    }

    @Test
    void producesMappedArisstoExampleWithoutCashTurnover() {
        try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
            oldPayoff();
            entry(10, 3, 1, portfolio, true, "238.99");
            entry(10, 3, 1, cash, false, "238.99");
            var lines = assemble(c, "238.99");
            assertEquals(4, lines.size());
            assertTrue(lines.stream().noneMatch(e -> e.getGlAccount() == cash));
            assertTrue(lines.stream().anyMatch(e -> e.getEntityId().equals(9L) && e.getAmount().compareTo(new BigDecimal("158.83")) == 0));
            assertEquals(1, lines.stream().filter(e -> e.isDebitEntry() && e.getAmount().compareTo(new BigDecimal("400")) == 0).count());
        }
        assertNull(RefinancingJournalContext.current());
    }

    @Test
    void retentionAndFeesCreateNoPayableOrCash() {
        try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
            oldPayoff();
            entry(10, 3, 1, portfolio, true, "238.99");
            entry(10, 3, 1, cash, false, "238.99");
            entry(10, 4, 5, cash, true, "10");
            entry(10, 4, 5, fees, false, "10");
            entry(10, 5, 2, cash, true, "228.99");
            entry(10, 5, 2, portfolio, false, "220");
            entry(10, 5, 2, interest, false, "8.99");
            var lines = assemble(c, "0");
            assertTrue(lines.stream().noneMatch(e -> e.getGlAccount() == cash || e.getGlAccount() == payable));
            assertTrue(lines.stream().anyMatch(e -> e.getGlAccount() == fees));
        }
    }

    @Test
    void nativeSavingsTransferCounterpartRemains() {
        try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
            oldPayoff();
            entry(10, 3, 1, portfolio, true, "238.99");
            entry(10, 3, 1, savings, false, "238.99");
            var lines = assemble(c, "0");
            assertTrue(lines.stream().anyMatch(e -> e.getGlAccount() == savings && e.isCreditEntry()));
            assertTrue(lines.stream().noneMatch(e -> e.getGlAccount() == cash || e.getGlAccount() == payable));
        }
    }

    @Test
    void mismatchedPayableFailsClosed() {
        try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
            oldPayoff();
            entry(10, 3, 1, portfolio, true, "238.99");
            entry(10, 3, 1, cash, false, "238.99");
            assertThrows(IllegalStateException.class, () -> assemble(c, "239"));
        }
    }

    @Test
    void excludesUnrelatedPredecessorReplayAndClearsOnFailure() {
        assertThrows(IllegalArgumentException.class, () -> {
            try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
                RefinancingJournalContext.register(9L, 100L, 2, date, false);
                assertTrue(c.transactionIds().isEmpty());
                throw new IllegalArgumentException();
            }
        });
        assertNull(RefinancingJournalContext.current());
    }

    @Test
    void reversalOnlySuppressesOwnedTransactions() {
        try (var ignored = RefinancingJournalContext.reverse(10L, Set.of(9L, 10L), Set.of(1L, 2L), date)) {
            assertTrue(RefinancingJournalContext.suppress(1L));
            assertFalse(RefinancingJournalContext.suppress(3L));
            assertFalse(RefinancingJournalContext.isOrigination(10L));
        }
        assertFalse(RefinancingJournalContext.suppress(1L));
    }

    @Test
    void combinedJournalPreservesEachLoansOffice() {
        try (var c = RefinancingJournalContext.open(10L, Set.of(9L, 10L), date)) {
            oldPayoff();
            entry(10, 3, 1, portfolio, true, "238.99");
            entry(10, 3, 1, cash, false, "238.99");
            var lines = assemble(c, "238.99");
            assertTrue(lines.stream().filter(e -> e.getEntityId().equals(9L)).allMatch(e -> e.getOffice() == predecessorOffice));
            assertTrue(lines.stream().filter(e -> e.getEntityId().equals(10L)).allMatch(e -> e.getOffice() == office));
        }
    }

}
