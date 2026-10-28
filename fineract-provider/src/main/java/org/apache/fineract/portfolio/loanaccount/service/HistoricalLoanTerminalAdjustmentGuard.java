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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfiguration;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfigurationRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffLifecycleState;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Native evidence for closing a paid historical loan after its client moved offices. */
@Service
@RequiredArgsConstructor
public class HistoricalLoanTerminalAdjustmentGuard {
    private final AccountingCutoffConfigurationRepository cutoffRepository;
    private final JdbcTemplate jdbc;

    public void validateRequest(Loan loan, LocalDate day, ExternalId transactionId) {
        String id = loan.getExternalId() == null ? null : loan.getExternalId().getValue();
        if (!SourceExactTerminalAdjustmentContext.isActive() || !SourceExactTerminalAdjustmentContext.isArisstoLoan(loan)
                || transactionId == null || !id.replace("ARISSTO:CRD:", "ARISSTO:CRD-CUTOVER:").equals(transactionId.getValue())) {
            throw invalid("Historical terminal adjustment requires the exact source loan and adjustment identity");
        }
        var cutoff = cutoffRepository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID)
                .orElseThrow(() -> invalid("An active accounting cutoff is required"));
        if (day == null || cutoff.getLifecycleState() != AccountingCutoffLifecycleState.ACTIVE
                || !day.isBefore(cutoff.getCutoffDate())) {
            throw invalid("Historical terminal adjustment must precede Fineract accounting ownership");
        }
    }

    public Office resolvePriorOffice(Loan loan, LocalDate day, ExternalId adjustmentId, boolean sourceExact, boolean goodwill) {
        if (!SourceExactTerminalAdjustmentContext.isActive() || !sourceExact || !goodwill
                || !SourceExactTerminalAdjustmentContext.isArisstoLoan(loan) || loan.isInterestRecalculationEnabled()
                || loan.getClient() == null || loan.getClient().getOfficeJoiningDate() == null
                || !day.isBefore(loan.getClient().getOfficeJoiningDate())
                || loan.getSummary().getTotalPrincipalOutstanding() == null
                || loan.getSummary().getTotalPrincipalOutstanding().abs().compareTo(new BigDecimal("0.01")) > 0) {
            return null;
        }
        validateRequest(loan, day, adjustmentId);
        Office payoffOffice = null;
        for (LoanTransaction transaction : loan.getLoanTransactions()) {
            if (transaction.isReversed()) continue;
            if (transaction.getTransactionDate().isAfter(day)) return null;
            String id = transaction.getExternalId().getValue();
            if (transaction.isRepayment() && transaction.getTransactionDate().equals(day)
                    && id != null && id.matches("(?:PROOF:[a-z0-9][a-z0-9-]{0,23}:)?ARISSTO:CRD-MOV:[0-9]+")) {
                Office office = transaction.getOffice();
                if (office == null || payoffOffice != null && !payoffOffice.getId().equals(office.getId())) return null;
                payoffOffice = office;
            }
        }
        if (payoffOffice == null) return null;
        List<OfficeTransfer> history = jdbc.query(
                "SELECT from_office_id,to_office_id,proposed_transfer_date FROM m_client_transfer_details "
                        + "WHERE client_id=? AND transfer_type=2 ORDER BY proposed_transfer_date DESC,id DESC",
                (rs, row) -> new OfficeTransfer(rs.getLong(1), rs.getLong(2), rs.getDate(3) == null ? null : rs.getDate(3).toLocalDate()),
                loan.getClientId());
        // Loan.getOffice() follows the client's current office. The immutable
        // recorded terminal repayment is the authority for this historical posting's office.
        return historicalOfficeMatches(loan.getClient().getOffice().getId(), payoffOffice.getId(), day, history)
                ? payoffOffice : null;
    }

    static boolean historicalOfficeMatches(Long currentOffice, Long receiptOffice, LocalDate day, List<OfficeTransfer> history) {
        boolean crossed = false;
        var dates = new HashSet<LocalDate>();
        for (OfficeTransfer transfer : history) {
            if (transfer.day() == null || !dates.add(transfer.day())) return false;
            if (!transfer.day().isAfter(day)) break;
            if (!currentOffice.equals(transfer.toOffice())) return false;
            currentOffice = transfer.fromOffice();
            crossed = true;
        }
        return crossed && currentOffice.equals(receiptOffice);
    }

    record OfficeTransfer(Long fromOffice, Long toOffice, LocalDate day) {}

    private static GeneralPlatformDomainRuleException invalid(String detail) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.historical.terminal.adjustment.invalid", detail);
    }
}
