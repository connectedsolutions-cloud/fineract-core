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

import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.cutoff.AccountingPostingOrigin;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.infrastructure.event.business.domain.journalentry.LoanJournalEntryCreatedBusinessEvent;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.accounting.journalentry.service.JournalNumberAllocationService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class JournalEntryPersistenceServiceImpl implements JournalEntryPersistenceService {

    private final JournalEntryRepository repository;
    private final AccountingCutoffPolicyService cutoffPolicyService;
    private final BusinessEventNotifierService businessEventNotifierService;
    private final AccountingPostingContext postingContext;
    private final JournalNumberAllocationService journalReferenceNumberService;

    @Override
    @Transactional
    public JournalEntry saveAndFlush(JournalEntry journalEntry) {
        cutoffPolicyService.assertJournalPersistenceAllowed(journalEntry.getTransactionDate());
        boolean isNew = journalEntry.isNew();
        if (isNew) {
            if (journalEntry.getTransactionId() == null || journalEntry.getTransactionId().isBlank()) {
                throw new IllegalArgumentException("A journal transaction id is required before number allocation");
            }
            String groupKey = journalEntry.getJournalNumberGroupKey();
            if (groupKey == null) {
                groupKey = journalEntry.getTransactionId() + "|" + journalEntry.getTransactionDate();
            }
            String number = postingContext.getOrigin() == AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT
                    ? journalReferenceNumberService.reserveImported(groupKey, journalEntry.getTransactionId(), journalEntry.getReferenceNumber())
                    : journalReferenceNumberService.assign(groupKey, journalEntry.getTransactionDate());
            journalEntry.setReferenceNumber(number);
        }
        JournalEntry savedJournalEntry = repository.saveAndFlush(journalEntry);
        if (isNew && journalEntry.getLoanTransactionId() != null) {
            businessEventNotifierService.notifyPostBusinessEvent(new LoanJournalEntryCreatedBusinessEvent(savedJournalEntry));
        }
        return savedJournalEntry;
    }
}
