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

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;

/** Transaction-local assembly of a refinance journal. Ordinary and source-import postings are unaffected. */
public final class RefinancingJournalContext implements AutoCloseable {

    private static final ThreadLocal<RefinancingJournalContext> CURRENT = new ThreadLocal<>();
    private final Long successorId;
    private final Set<Long> loanIds;
    private final LocalDate date;
    private final boolean reversing;
    private final Map<Long, Integer> transactionTypes = new HashMap<>();
    private final List<JournalEntry> entries = new ArrayList<>();

    private RefinancingJournalContext(Long successorId, Set<Long> loanIds, LocalDate date, boolean reversing) {
        if (CURRENT.get() != null) {
            throw new IllegalStateException("Nested refinancing accounting context");
        }
        this.successorId = successorId;
        this.loanIds = Set.copyOf(loanIds);
        this.date = date;
        this.reversing = reversing;
        CURRENT.set(this);
    }

    public static RefinancingJournalContext open(Long loanId, Set<Long> loanIds, LocalDate date) {
        return new RefinancingJournalContext(loanId, loanIds, date, false);
    }

    public static RefinancingJournalContext reverse(Long loanId, Set<Long> loanIds, Set<Long> transactionIds, LocalDate date) {
        RefinancingJournalContext context = new RefinancingJournalContext(loanId, loanIds, date, true);
        transactionIds.forEach(id -> context.transactionTypes.put(id, 0));
        return context;
    }

    public static RefinancingJournalContext current() {
        return CURRENT.get();
    }

    public static boolean isOrigination(Long loanId) {
        RefinancingJournalContext c = CURRENT.get();
        return c != null && !c.reversing && c.successorId.equals(loanId);
    }

    public static boolean suppress(Long transactionId) {
        RefinancingJournalContext c = CURRENT.get();
        return c != null && c.reversing && c.transactionTypes.containsKey(transactionId);
    }

    public static void register(Long loanId, Long transactionId, Integer type, LocalDate date, boolean loanToLoanTransfer) {
        RefinancingJournalContext c = CURRENT.get();
        if (c != null && !c.reversing && c.loanIds.contains(loanId) && c.date.equals(date) && Set.of(1, 2, 5, 46).contains(type)
                && (c.successorId.equals(loanId) || (type == 2 && loanToLoanTransfer))) {
            c.transactionTypes.put(transactionId, type);
        }
    }

    public static boolean capture(JournalEntry entry) {
        RefinancingJournalContext c = CURRENT.get();
        if (c == null || c.reversing || !c.loanIds.contains(entry.getEntityId())
                || !c.transactionTypes.containsKey(entry.getLoanTransactionId()) || !c.date.equals(entry.getTransactionDate())) {
            return false;
        }
        if (entry.isReversed()) {
            throw new IllegalStateException("Unexpected reversal inside refinance origination");
        }
        c.entries.add(entry);
        return true;
    }

    public List<JournalEntry> entries() {
        return List.copyOf(entries);
    }

    public Set<Long> transactionIds() {
        return new HashSet<>(transactionTypes.keySet());
    }

    public Integer type(Long transactionId) {
        return transactionTypes.get(transactionId);
    }

    public LocalDate date() {
        return date;
    }

    @Override
    public void close() {
        CURRENT.remove();
    }
}
