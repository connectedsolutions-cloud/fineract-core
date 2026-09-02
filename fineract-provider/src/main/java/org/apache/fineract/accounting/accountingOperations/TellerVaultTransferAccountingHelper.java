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
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Creates GL entries for teller/vault cash movements tied to pending-flow approval. From teller: debit main vault,
 * credit cash-at-teller (SETTLE semantics). To teller: debit cash-at-teller, credit main vault (ALLOCATE semantics).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TellerVaultTransferAccountingHelper {

    private static final String TXN_PREFIX = "PEND-VAULT-";
    private static final String TXN_PREFIX_REQUEST = "PEND-REQ-";

    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository;
    private final AccountingProcessorHelper accountingProcessorHelper;

    /**
     * Posts the vault transfer: Debit main vault, Credit cash-at-teller. Uses the same account logic as SETTLE in
     * TellerWritePlatformServiceJpaImpl.
     *
     * @param office
     *            office for the entries
     * @param amount
     *            amount to transfer
     * @param currencyCode
     *            currency code
     * @param transactionDate
     *            business/transaction date
     * @param transactionId
     *            unique transaction id (e.g. from pending flow/step)
     * @param description
     *            optional note for the entries
     */
    @Transactional
    public void postVaultTransferFromTeller(Office office, BigDecimal amount, String currencyCode, LocalDate transactionDate,
            String transactionId, String description) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            log.warn("TellerVaultTransferAccountingHelper: amount must be positive, got {}", amount);
            return;
        }
        if (office == null || currencyCode == null || transactionId == null) {
            log.warn("TellerVaultTransferAccountingHelper: office, currencyCode and transactionId are required");
            return;
        }

        GLAccount mainVaultAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_MAINVAULT.getValue()).getGlAccount();
        GLAccount cashAtTellerAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_TELLER.getValue()).getGlAccount();

        JournalEntry debitEntry = JournalEntry.createNew(office, null, mainVaultAccount, currencyCode, transactionId, false,
                transactionDate, JournalEntryType.DEBIT, amount, description, null, null, null, null, null, null, null, null);
        JournalEntry creditEntry = JournalEntry.createNew(office, null, cashAtTellerAccount, currencyCode, transactionId, false,
                transactionDate, JournalEntryType.CREDIT, amount, description, null, null, null, null, null, null, null, null);

        accountingProcessorHelper.persistJournalEntry(debitEntry);
        accountingProcessorHelper.persistJournalEntry(creditEntry);

        log.debug("TellerVaultTransferAccountingHelper: posted vault transfer txnId={} amount={} office={}", transactionId, amount,
                office.getId());
    }

    /**
     * Posts vault-to-teller allocation: Debit cash-at-teller, Credit main vault (same as ALLOCATE in teller).
     */
    @Transactional
    public void postVaultTransferToTeller(Office office, BigDecimal amount, String currencyCode, LocalDate transactionDate,
            String transactionId, String description) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            log.warn("TellerVaultTransferAccountingHelper: amount must be positive, got {}", amount);
            return;
        }
        if (office == null || currencyCode == null || transactionId == null) {
            log.warn("TellerVaultTransferAccountingHelper: office, currencyCode and transactionId are required");
            return;
        }

        GLAccount mainVaultAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_MAINVAULT.getValue()).getGlAccount();
        GLAccount cashAtTellerAccount = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_TELLER.getValue()).getGlAccount();

        JournalEntry debitEntry = JournalEntry.createNew(office, null, cashAtTellerAccount, currencyCode, transactionId, false,
                transactionDate, JournalEntryType.DEBIT, amount, description, null, null, null, null, null, null, null, null);
        JournalEntry creditEntry = JournalEntry.createNew(office, null, mainVaultAccount, currencyCode, transactionId, false,
                transactionDate, JournalEntryType.CREDIT, amount, description, null, null, null, null, null, null, null, null);

        accountingProcessorHelper.persistJournalEntry(debitEntry);
        accountingProcessorHelper.persistJournalEntry(creditEntry);

        log.debug("TellerVaultTransferAccountingHelper: posted vault-to-teller txnId={} amount={} office={}", transactionId, amount,
                office.getId());
    }

    /**
     * Generates a unique transaction id for the pending-flow vault transfer.
     */
    public static String generateTransactionId(Long flowId, Long stepId) {
        long time = System.currentTimeMillis();
        return TXN_PREFIX + (flowId != null ? flowId : "0") + "-" + (stepId != null ? stepId : "0") + "-" + Long.toHexString(time);
    }

    /**
     * Generates a unique transaction id for requerir-fondos-caja-boveda (vault to teller).
     */
    public static String generateRequestVaultTransactionId(Long flowId, Long stepId) {
        long time = System.currentTimeMillis();
        return TXN_PREFIX_REQUEST + (flowId != null ? flowId : "0") + "-" + (stepId != null ? stepId : "0") + "-" + Long.toHexString(time);
    }
}
