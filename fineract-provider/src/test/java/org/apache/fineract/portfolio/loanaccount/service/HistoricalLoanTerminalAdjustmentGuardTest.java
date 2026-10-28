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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfiguration;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfigurationRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffLifecycleState;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanSummary;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class HistoricalLoanTerminalAdjustmentGuardTest {
    private static final LocalDate DAY = LocalDate.of(2024, 10, 16);
    private static final LocalDate MOVED = LocalDate.of(2024, 11, 27);

    @Test
    void sourceOwnedPaidTerminalCreditCanUseItsProvenHistoricalOfficeOnlyInGuardedContext() {
        var repo = mock(AccountingCutoffConfigurationRepository.class);
        var cutoff = mock(AccountingCutoffConfiguration.class);
        when(repo.findByIdForUpdate(1L)).thenReturn(Optional.of(cutoff));
        when(cutoff.getLifecycleState()).thenReturn(AccountingCutoffLifecycleState.ACTIVE);
        when(cutoff.getCutoffDate()).thenReturn(LocalDate.of(2026, 10, 27));
        var jdbc = mock(JdbcTemplate.class);
        var guard = new HistoricalLoanTerminalAdjustmentGuard(repo, jdbc);
        Loan loan = mock(Loan.class);
        when(loan.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD:1"));
        Client client = mock(Client.class); Office office = mock(Office.class);
        when(loan.getClient()).thenReturn(client); when(loan.getClientId()).thenReturn(1L);
        when(client.getOfficeJoiningDate()).thenReturn(MOVED); when(client.getOffice()).thenReturn(office);
        when(office.getId()).thenReturn(2L); when(loan.getOfficeId()).thenReturn(1L);
        var summary = mock(LoanSummary.class); when(loan.getSummary()).thenReturn(summary);
        when(summary.getTotalPrincipalOutstanding()).thenReturn(BigDecimal.ZERO);
        LoanTransaction adjustment = mock(LoanTransaction.class), payoff = mock(LoanTransaction.class);
        when(adjustment.isGoodwillCredit()).thenReturn(true); when(adjustment.getTransactionDate()).thenReturn(DAY);
        when(adjustment.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD-CUTOVER:1"));
        when(payoff.getTransactionDate()).thenReturn(DAY); when(payoff.isRepayment()).thenReturn(true);
        when(payoff.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD-MOV:1"));
        when(loan.getLoanTransactions()).thenReturn(List.of(payoff));
        when(jdbc.query(anyString(), ArgumentMatchers.<RowMapper<HistoricalLoanTerminalAdjustmentGuard.OfficeTransfer>>any(), eq(1L)))
                .thenReturn(List.of(new HistoricalLoanTerminalAdjustmentGuard.OfficeTransfer(1L, 2L, MOVED)));
        assertFalse(guard.permitsPriorOfficeDate(loan, adjustment, true));
        SourceExactTerminalAdjustmentContext.execute(() -> {
            assertTrue(guard.permitsPriorOfficeDate(loan, adjustment, true));
            assertFalse(guard.permitsPriorOfficeDate(loan, adjustment, false));
            when(loan.isInterestRecalculationEnabled()).thenReturn(true);
            assertFalse(guard.permitsPriorOfficeDate(loan, adjustment, true));
            when(loan.isInterestRecalculationEnabled()).thenReturn(false);
            when(summary.getTotalPrincipalOutstanding()).thenReturn(BigDecimal.ONE);
            assertFalse(guard.permitsPriorOfficeDate(loan, adjustment, true));
            when(summary.getTotalPrincipalOutstanding()).thenReturn(BigDecimal.ZERO);
            when(payoff.isReversed()).thenReturn(true);
            assertFalse(guard.permitsPriorOfficeDate(loan, adjustment, true));
            when(payoff.isReversed()).thenReturn(false);
            assertThrows(RuntimeException.class, () -> guard.validateRequest(loan, cutoff.getCutoffDate(), adjustment.getExternalId()));
            assertThrows(RuntimeException.class, () -> guard.validateRequest(loan, DAY, new ExternalId("ARISSTO:CRD-CUTOVER:2")));
            return null;
        });
    }

    @Test
    void officeProofMustFormAnUnambiguousChainToTheLoanOffice() {
        var history = List.of(new HistoricalLoanTerminalAdjustmentGuard.OfficeTransfer(2L, 3L, MOVED.plusDays(30)),
                new HistoricalLoanTerminalAdjustmentGuard.OfficeTransfer(1L, 2L, MOVED));
        assertTrue(HistoricalLoanTerminalAdjustmentGuard.historicalOfficeMatches(3L, 1L, DAY, history));
        assertFalse(HistoricalLoanTerminalAdjustmentGuard.historicalOfficeMatches(4L, 1L, DAY, history));
        assertFalse(HistoricalLoanTerminalAdjustmentGuard.historicalOfficeMatches(3L, 4L, DAY, history));
        assertFalse(HistoricalLoanTerminalAdjustmentGuard.historicalOfficeMatches(3L, 1L, DAY, List.of()));
    }
}
