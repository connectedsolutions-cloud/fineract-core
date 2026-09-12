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

import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

class JournalEntryPersistenceServiceImplTest {

    @Test
    void assertsCutoffBeforeRepositoryWrite() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingCutoffPolicyService policy = mock(AccountingCutoffPolicyService.class);
        BusinessEventNotifierService notifier = mock(BusinessEventNotifierService.class);
        JournalEntry journalEntry = mock(JournalEntry.class);
        LocalDate date = LocalDate.of(2026, 10, 1);
        when(journalEntry.getTransactionDate()).thenReturn(date);
        when(repository.saveAndFlush(journalEntry)).thenReturn(journalEntry);
        new JournalEntryPersistenceServiceImpl(repository, policy, notifier).saveAndFlush(journalEntry);
        InOrder order = inOrder(policy, repository);
        order.verify(policy).assertJournalPersistenceAllowed(date);
        order.verify(repository).saveAndFlush(journalEntry);
    }
}
