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
package org.apache.fineract.accounting.accountingOperations;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.PortfolioProductType;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Creates session-level GL entries for "available at cashier" flow after comite otorgamiento:
 * vaultReceptionFromBank (tx-1): Fund source (credit) / Vault (debit);
 * cashierCashReception (tx-2): Vault (credit) / Cash-at-teller (debit);
 * disbursementPayableClearing (tx-3): Cash-at-teller (credit) / Disbursement payable (debit, one per loan).
 *
 * Each transaction can be triggered separately or all at once via createAvailableAtCashierEntries.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AvailableAtCashierAccountingHelper {

    private static final String COMTE_TXN_PREFIX = "COMTE-S";

    private final AccountingProcessorHelper accountingProcessorHelper;
    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository;

    /**
     * Returns the sum of {@link Loan#getNetDisbursalAmount()} for all loans in the list (nulls treated as zero).
     */
    public BigDecimal getTotalDisbursementAmountLoanBatch(List<Loan> loans) {
        if (loans == null || loans.isEmpty()) {
            return BigDecimal.ZERO;
        }
        return loans.stream()
                .map(Loan::getNetDisbursalAmount)
                .filter(a -> a != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    /**
     * Creates all three journal entries (vaultReceptionFromBank, cashierCashReception, disbursementPayableClearing)
     * for the comite session. Skips if processedLoans is empty or total disbursement is zero.
     */
    @Transactional
    public void createAvailableAtCashierEntries(SesionComite session, List<Loan> processedLoans, LocalDate businessDate) {
        vaultReceptionFromBank(session, processedLoans, businessDate);
        cashierCashReception(session, processedLoans, businessDate);
        disbursementPayableClearing(session, processedLoans, businessDate);
    }

    /**
     * Tx-1: Fund source (credit) / Vault (debit). Can be triggered separately.
     */
    @Transactional
    public void vaultReceptionFromBank(SesionComite session, List<Loan> processedLoans, LocalDate businessDate) {
        AtCashierContext ctx = buildContext(session, processedLoans);
        if (ctx == null) {
            return;
        }
        String txnId = COMTE_TXN_PREFIX + session.getId() + "-vaultReceptionFromBank";

        persistSessionLevelEntry(ctx.office(), ctx.currencyCode(), ctx.fundSourceAccount(), txnId, businessDate,
                JournalEntryType.CREDIT, ctx.total(), ctx.firstLoanId());
        persistSessionLevelEntry(ctx.office(), ctx.currencyCode(), ctx.vaultAccount(), txnId, businessDate,
                JournalEntryType.DEBIT, ctx.total(), ctx.firstLoanId());

        log.debug("AvailableAtCashier vaultReceptionFromBank: created entries for session {} total={}",
                session.getId(), ctx.total());
    }

    /**
     * Tx-2: Vault (credit) / Cash-at-teller (debit). Can be triggered separately.
     */
    @Transactional
    public void cashierCashReception(SesionComite session, List<Loan> processedLoans, LocalDate businessDate) {
        AtCashierContext ctx = buildContext(session, processedLoans);
        if (ctx == null) {
            return;
        }
        String txnId = COMTE_TXN_PREFIX + session.getId() + "-cashierCashReception";

        persistSessionLevelEntry(ctx.office(), ctx.currencyCode(), ctx.vaultAccount(), txnId, businessDate,
                JournalEntryType.CREDIT, ctx.total(), ctx.firstLoanId());
        persistSessionLevelEntry(ctx.office(), ctx.currencyCode(), ctx.cashAtTellerAccount(), txnId, businessDate,
                JournalEntryType.DEBIT, ctx.total(), ctx.firstLoanId());

        log.debug("AvailableAtCashier cashierCashReception: created entries for session {} total={}",
                session.getId(), ctx.total());
    }

    /**
     * Tx-3: Cash-at-teller (credit) / Disbursement payable (debit, one per loan). Can be triggered separately.
     */
    @Transactional
    public void disbursementPayableClearing(SesionComite session, List<Loan> processedLoans, LocalDate businessDate) {
        AtCashierContext ctx = buildContext(session, processedLoans);
        if (ctx == null) {
            return;
        }
        String txnId = COMTE_TXN_PREFIX + session.getId() + "-disbursementPayableClearing";

        persistSessionLevelEntry(ctx.office(), ctx.currencyCode(), ctx.cashAtTellerAccount(), txnId, businessDate,
                JournalEntryType.CREDIT, ctx.total(), ctx.firstLoanId());
        for (Loan loan : processedLoans) {
            BigDecimal amount = loan.getNetDisbursalAmount();
            if (amount != null && amount.compareTo(BigDecimal.ZERO) > 0) {
                persistLoanLevelDebitEntry(ctx.office(), ctx.currencyCode(), ctx.disbursementsPayableAccount(),
                        txnId, businessDate, amount, loan.getId(), loan.getDimensions());
            }
        }

        log.debug("AvailableAtCashier disbursementPayableClearing: created entries for session {} total={} loans={}",
                session.getId(), ctx.total(), processedLoans.size());
    }

    /**
     * Builds the context (GL accounts, totals, etc.) for the at-cashier operations.
     * Returns null if processedLoans is empty or total disbursement is zero.
     */
    private AtCashierContext buildContext(SesionComite session, List<Loan> processedLoans) {
        if (processedLoans == null || processedLoans.isEmpty()) {
            log.debug("AvailableAtCashier: no processed loans for session {}, skipping", session.getId());
            return null;
        }

        BigDecimal total = getTotalDisbursementAmountLoanBatch(processedLoans);
        if (total.compareTo(BigDecimal.ZERO) <= 0) {
            log.debug("AvailableAtCashier: total disbursement is zero for session {}, skipping", session.getId());
            return null;
        }

        Loan firstLoan = processedLoans.get(0);
        Office office = firstLoan.getOffice();
        String currencyCode = firstLoan.getCurrencyCode();
        Long firstLoanId = firstLoan.getId();
        Long loanProductId = firstLoan.getLoanProduct() != null ? firstLoan.getLoanProduct().getId() : null;
        Long paymentTypeId = firstLoan.getDisbursalMethodPaymentType() != null
                ? firstLoan.getDisbursalMethodPaymentType().getId()
                : null;

        GLAccount fundSourceAccount = accountingProcessorHelper.getLinkedGLAccountForLoanProduct(loanProductId,
                CashAccountsForLoan.FUND_SOURCE.getValue(), paymentTypeId);
        GLAccount vaultAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_MAINVAULT.getValue())
                .getGlAccount();
        GLAccount cashAtTellerAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_TELLER.getValue())
                .getGlAccount();
        GLAccount disbursementsPayableAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.DISBURSEMENTS_PAYABLE.getValue())
                .getGlAccount();

        return new AtCashierContext(office, currencyCode, total, firstLoanId, fundSourceAccount, vaultAccount,
                cashAtTellerAccount, disbursementsPayableAccount);
    }

    private record AtCashierContext(Office office, String currencyCode, BigDecimal total, Long firstLoanId,
            GLAccount fundSourceAccount, GLAccount vaultAccount, GLAccount cashAtTellerAccount,
            GLAccount disbursementsPayableAccount) {}

    private void persistSessionLevelEntry(Office office, String currencyCode, GLAccount account, String transactionId,
            LocalDate transactionDate, JournalEntryType type, BigDecimal amount, Long entityLoanId) {
        JournalEntry entry = JournalEntry.createNew(office, null, account, currencyCode, transactionId, false,
                transactionDate, type, amount, null, PortfolioProductType.LOAN.getValue(), entityLoanId, null,
                null, null, null, null, null);
        accountingProcessorHelper.persistJournalEntry(entry);
    }

    private void persistLoanLevelDebitEntry(Office office, String currencyCode, GLAccount account, String transactionId,
            LocalDate transactionDate, BigDecimal amount, Long loanId, String dimensions) {
        JournalEntry entry = JournalEntry.createNew(office, null, account, currencyCode, transactionId, false,
                transactionDate, JournalEntryType.DEBIT, amount, null, PortfolioProductType.LOAN.getValue(), loanId,
                null, null, null, null, null, dimensions);
        accountingProcessorHelper.persistJournalEntry(entry);
    }
}
