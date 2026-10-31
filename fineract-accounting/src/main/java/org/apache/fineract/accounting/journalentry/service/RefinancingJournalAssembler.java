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

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;

/** Converts native loan-component entries into a single balanced origination event without false fund turnover. */
public final class RefinancingJournalAssembler {

    private RefinancingJournalAssembler() {}

    public static List<JournalEntry> assemble(RefinancingJournalContext context, Long loanId, BigDecimal principal, Long portfolioAccountId,
            Set<Long> internalFundsAccountIds, GLAccount payableAccount, BigDecimal payableAmount) {
        List<JournalEntry> result = new ArrayList<>();
        BigDecimal principalDebits = BigDecimal.ZERO;
        JournalEntry principalTemplate = null;
        for (JournalEntry entry : context.entries()) {
            int type = context.type(entry.getLoanTransactionId());
            if (type == 1 && Objects.equals(entry.getEntityId(), loanId) && entry.isDebitEntry()
                    && Objects.equals(entry.getGlAccount().getId(), portfolioAccountId)) {
                principalDebits = principalDebits.add(entry.getAmount());
                if (principalTemplate == null) {
                    principalTemplate = entry;
                }
            } else if (internalFundsAccountIds.contains(entry.getGlAccount().getId())
                    && ((type == 1 && entry.isCreditEntry()) || ((type == 2 || type == 5 || type == 46) && entry.isDebitEntry()))) {
                // Loan-to-loan offset, cash-disbursement fund source, or fee/tax funding: represented by final
                // components instead.
            } else {
                result.add(entry);
            }
        }
        if (principalTemplate == null || principalDebits.compareTo(principal) != 0) {
            throw new IllegalStateException("Refinancing principal entries do not equal the contractual disbursement");
        }
        result.add(copy(principalTemplate, principalTemplate.getGlAccount(), JournalEntryType.DEBIT, principal));
        if (payableAmount.signum() < 0) {
            throw new IllegalStateException("Negative refinancing payout");
        }
        if (payableAmount.signum() > 0) {
            result.add(copy(principalTemplate, payableAccount, JournalEntryType.CREDIT, payableAmount));
        }
        validateBalanced(result);
        return result;
    }

    private static JournalEntry copy(JournalEntry template, GLAccount account, JournalEntryType side, BigDecimal amount) {
        return JournalEntry.createNew(template.getOffice(), null, account, template.getCurrencyCode(), template.getTransactionId(), false,
                template.getTransactionDate(), side, amount, "Loan refinancing", template.getEntityType(), template.getEntityId(), null,
                template.getLoanTransactionId(), null, null, null, template.getDimensions());
    }

    public static void validateBalanced(List<JournalEntry> entries) {
        if (entries.isEmpty()) {
            throw new IllegalStateException("Empty refinancing journal");
        }
        String currency = entries.getFirst().getCurrencyCode();
        BigDecimal net = BigDecimal.ZERO;
        for (JournalEntry entry : entries) {
            if (!Objects.equals(currency, entry.getCurrencyCode()) || entry.getAmount().signum() <= 0) {
                throw new IllegalStateException("Invalid currency or non-positive refinancing journal entry");
            }
            net = net.add(entry.isDebitEntry() ? entry.getAmount() : entry.getAmount().negate());
        }
        if (net.signum() != 0) {
            throw new IllegalStateException("Unbalanced refinancing journal: " + net);
        }
    }
}
