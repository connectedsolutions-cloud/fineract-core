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

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.cutoff.AccountingPostingOrigin;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

class JournalEntryPersistenceServiceImplTest {

    private static final LocalDate IMPORT_DATE = LocalDate.of(2026, 9, 17);

    private JournalEntry importedLine(String transactionId) {
        JournalEntry entry = mock(JournalEntry.class);
        when(entry.isNew()).thenReturn(true);
        when(entry.getTransactionId()).thenReturn(transactionId);
        when(entry.getTransactionDate()).thenReturn(IMPORT_DATE);
        when(entry.getReferenceNumber()).thenReturn("2026090446");
        when(entry.getLoanTransactionId()).thenReturn(null);
        when(entry.getSavingsTransactionId()).thenReturn(null);
        when(entry.getClientTransactionId()).thenReturn(null);
        when(entry.getShareTransactionId()).thenReturn(null);
        when(entry.getEntityId()).thenReturn(null);
        return entry;
    }

    @Test
    void assertsCutoffBeforeRepositoryWrite() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingCutoffPolicyService policy = mock(AccountingCutoffPolicyService.class);
        BusinessEventNotifierService notifier = mock(BusinessEventNotifierService.class);
        JournalEntry journalEntry = mock(JournalEntry.class);
        LocalDate date = LocalDate.of(2026, 10, 1);
        when(journalEntry.getTransactionDate()).thenReturn(date);
        when(repository.saveAndFlush(journalEntry)).thenReturn(journalEntry);
        new JournalEntryPersistenceServiceImpl(repository, policy, notifier, mock(AccountingPostingContext.class),
                mock(JournalNumberAllocationService.class)).saveAndFlush(journalEntry);
        InOrder order = inOrder(policy, repository);
        order.verify(policy).assertJournalPersistenceAllowed(date);
        order.verify(repository).saveAndFlush(journalEntry);
    }

    @Test
    void assignsNativeNumberAtSharedPersistenceBoundary() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingPostingContext context = mock(AccountingPostingContext.class);
        JournalNumberAllocationService numbers = mock(JournalNumberAllocationService.class);
        JournalEntry entry = mock(JournalEntry.class);
        LocalDate date = LocalDate.of(2026, 9, 18);
        when(entry.isNew()).thenReturn(true);
        when(entry.getTransactionDate()).thenReturn(date);
        when(entry.getTransactionId()).thenReturn("L123");
        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.NATIVE_OPERATION);
        when(numbers.assign("L123|2026-09-18", date)).thenReturn("2026090451");
        when(repository.saveAndFlush(entry)).thenReturn(entry);
        new JournalEntryPersistenceServiceImpl(repository, mock(AccountingCutoffPolicyService.class),
                mock(BusinessEventNotifierService.class), context, numbers).saveAndFlush(entry);
        verify(entry).setReferenceNumber("2026090451");
    }

    @Test
    void preservesImportedNumberThroughPrivilegedReservation() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingPostingContext context = mock(AccountingPostingContext.class);
        JournalNumberAllocationService numbers = mock(JournalNumberAllocationService.class);
        JournalEntry entry = mock(JournalEntry.class);
        when(entry.isNew()).thenReturn(true);
        when(entry.getTransactionDate()).thenReturn(LocalDate.of(2026, 9, 17));
        when(entry.getTransactionId()).thenReturn("AI123");
        when(entry.getReferenceNumber()).thenReturn("2026090446");
        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT);
        when(numbers.reserveImported("AI123|2026-09-17", "AI123", "2026090446")).thenReturn("2026090446");
        when(repository.saveAndFlush(entry)).thenReturn(entry);
        new JournalEntryPersistenceServiceImpl(repository, mock(AccountingCutoffPolicyService.class),
                mock(BusinessEventNotifierService.class), context, numbers).saveAndFlush(entry);
        verify(entry).setReferenceNumber("2026090446");
    }

    @Test
    void importedJournalReservesOnceAndFlushesOnceAfterAllLines() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingCutoffPolicyService policy = mock(AccountingCutoffPolicyService.class);
        AccountingPostingContext context = mock(AccountingPostingContext.class);
        JournalNumberAllocationService numbers = mock(JournalNumberAllocationService.class);
        JournalEntry first = importedLine("AI123");
        JournalEntry second = importedLine("AI123");
        List<JournalEntry> lines = List.of(first, second);
        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT);
        when(numbers.reserveImported("AI123|2026-09-17", "AI123", "2026090446")).thenReturn("2026090446");
        when(repository.saveAll(lines)).thenReturn(lines);

        new JournalEntryPersistenceServiceImpl(repository, policy, mock(BusinessEventNotifierService.class), context, numbers)
                .saveImportedJournal(lines);

        verify(policy, org.mockito.Mockito.times(2)).assertJournalPersistenceAllowed(IMPORT_DATE);
        verify(numbers).reserveImported("AI123|2026-09-17", "AI123", "2026090446");
        InOrder order = inOrder(numbers, repository);
        order.verify(numbers).reserveImported("AI123|2026-09-17", "AI123", "2026090446");
        order.verify(repository).saveAll(lines);
        order.verify(repository).flush();
    }

    @Test
    void importedJournalRejectsWrongOriginAndMixedIdentityBeforeWriting() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingPostingContext context = mock(AccountingPostingContext.class);
        JournalNumberAllocationService numbers = mock(JournalNumberAllocationService.class);
        JournalEntry first = importedLine("AI123");
        JournalEntry other = importedLine("AI456");
        JournalEntryPersistenceServiceImpl service = new JournalEntryPersistenceServiceImpl(repository,
                mock(AccountingCutoffPolicyService.class), mock(BusinessEventNotifierService.class), context, numbers);

        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.NATIVE_OPERATION);
        assertThatThrownBy(() -> service.saveImportedJournal(List.of(first))).isInstanceOf(IllegalArgumentException.class);
        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT);
        assertThatThrownBy(() -> service.saveImportedJournal(List.of(first, other))).isInstanceOf(IllegalArgumentException.class);
        verify(numbers, never()).reserveImported(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any());
        verify(repository, never()).saveAll(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void importedJournalStillChecksCutoffBeforeNumberReservation() {
        JournalEntryRepository repository = mock(JournalEntryRepository.class);
        AccountingCutoffPolicyService policy = mock(AccountingCutoffPolicyService.class);
        AccountingPostingContext context = mock(AccountingPostingContext.class);
        JournalNumberAllocationService numbers = mock(JournalNumberAllocationService.class);
        when(context.getOrigin()).thenReturn(AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT);
        org.mockito.Mockito.doThrow(new IllegalStateException("cutoff rejected")).when(policy).assertJournalPersistenceAllowed(IMPORT_DATE);

        JournalEntryPersistenceServiceImpl service = new JournalEntryPersistenceServiceImpl(repository, policy,
                mock(BusinessEventNotifierService.class), context, numbers);
        assertThatThrownBy(() -> service.saveImportedJournal(List.of(importedLine("AI123")))).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("cutoff rejected");
        verify(repository, never()).saveAll(org.mockito.ArgumentMatchers.any());
    }
}
