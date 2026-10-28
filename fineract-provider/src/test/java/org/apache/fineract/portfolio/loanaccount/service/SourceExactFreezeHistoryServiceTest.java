/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file distributed
 * with this work for additional information regarding copyright ownership. The ASF licenses this file to you under the Apache License,
 * Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions
 * and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.apache.fineract.accounting.cutoff.AccountingCutoffMigrationValidationService;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeAction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.junit.jupiter.api.Test;

class SourceExactFreezeHistoryServiceTest {
    private final LoanRepositoryWrapper repository = mock(LoanRepositoryWrapper.class);
    private final AccountingCutoffMigrationValidationService cutoff = mock(AccountingCutoffMigrationValidationService.class);
    private final SourceExactFreezeHistoryService service = new SourceExactFreezeHistoryService(repository, cutoff);
    private final Loan loan = mock(Loan.class);
    private final JsonCommand command = mock(JsonCommand.class);
    private final List<LoanFreezeHistory> history = new ArrayList<>();

    private void setup(LoanStatus status, LocalDate closed) {
        when(repository.findOneWithNotFoundDetection(1L, true)).thenReturn(loan);
        when(loan.getStatus()).thenReturn(status);
        when(loan.getClosedOnDate()).thenReturn(closed);
        when(loan.getDisbursementDate()).thenReturn(LocalDate.of(2025, 1, 1));
        when(loan.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD:1"));
        when(loan.getId()).thenReturn(1L);
        when(loan.getFreezeHistory()).thenReturn(history);
        when(command.json()).thenReturn("""
            {"sourceSystem":"ARISSTO","sourceLoanExternalId":"ARISSTO:CRD:1","cutoffDate":"2026-10-27",
             "events":[{"sourceEventId":10,"effectiveDate":"2026-09-01","blocked":true}]}
            """);
    }

    @Test
    void repaidBeforeCutoffImportsOngoingHistoricalFreezeWithoutFinancialReprocessing() {
        setup(LoanStatus.CLOSED_OBLIGATIONS_MET, LocalDate.of(2026, 10, 1));
        service.importHistory(1L, command);
        verify(loan).freeze(LocalDate.of(2026, 9, 1), "Arissto loan account restriction", "ARISSTO:AFI-BLOQUEO:10");
        verify(repository).saveAndFlush(loan);
        verify(loan, never()).getLoanTransactions();
        verify(loan, never()).getSummary();
        verify(cutoff).requireExactActiveCutoff(LocalDate.of(2026, 10, 27));
        assertEquals(LoanStatus.CLOSED_OBLIGATIONS_MET, loan.getStatus());
    }

    @Test
    void realRestrictionAfterHistoricalClosureRemainsDatedProvenanceBeforeCutoff() {
        setup(LoanStatus.CLOSED_OBLIGATIONS_MET, LocalDate.of(2026, 8, 1));
        service.importHistory(1L, command);
        verify(loan).freeze(LocalDate.of(2026, 9, 1), "Arissto loan account restriction", "ARISSTO:AFI-BLOQUEO:10");
        assertEquals(LocalDate.of(2026, 8, 1), loan.getClosedOnDate());
    }

    @Test
    void closedOnOrAfterFineractStartsAndUnprovedClosureRemainRejected() {
        for (LocalDate closed : new LocalDate[] {null, LocalDate.of(2026, 10, 27), LocalDate.of(2026, 10, 28)}) {
            setup(LoanStatus.CLOSED_OBLIGATIONS_MET, closed);
            assertThrows(RuntimeException.class, () -> service.importHistory(1L, command));
        }
        verify(repository, never()).saveAndFlush(any());
    }

    @Test
    void approvedUndisbursedAndWrittenOffLoansDoNotAcquireThisRepaidException() {
        for (LoanStatus status : new LoanStatus[] {LoanStatus.APPROVED, LoanStatus.SUBMITTED_AND_PENDING_APPROVAL,
                LoanStatus.CLOSED_WRITTEN_OFF}) {
            setup(status, LocalDate.of(2026, 10, 1));
            assertThrows(RuntimeException.class, () -> service.importHistory(1L, command));
        }
        verify(repository, never()).saveAndFlush(any());
    }

    @Test
    void identicalExistingClosedHistoryIsReadOnlyAndConflictingHistoryIsRejected() {
        setup(LoanStatus.CLOSED_OBLIGATIONS_MET, LocalDate.of(2026, 10, 1));
        history.add(new LoanFreezeHistory(loan, LoanFreezeAction.FREEZE, LocalDate.of(2026, 9, 1), "original",
                "ARISSTO:AFI-BLOQUEO:10"));
        service.importHistory(1L, command);
        verify(repository, never()).saveAndFlush(any());
        verify(loan, never()).freeze(any(), any(), any());
        history.add(new LoanFreezeHistory(loan, LoanFreezeAction.UNFREEZE, LocalDate.of(2026, 9, 2), "extra",
                "ARISSTO:AFI-BLOQUEO:11"));
        assertThrows(RuntimeException.class, () -> service.importHistory(1L, command));
    }

    @Test
    void activeHistoryKeepsItsExistingClosedBusinessDateGuard() {
        setup(LoanStatus.ACTIVE, null);
        when(loan.getLastClosedBusinessDate()).thenReturn(LocalDate.of(2026, 10, 1));
        assertThrows(RuntimeException.class, () -> service.importHistory(1L, command));
        verify(repository, never()).saveAndFlush(any());
    }
}
