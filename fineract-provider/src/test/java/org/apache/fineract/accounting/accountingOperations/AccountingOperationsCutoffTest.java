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

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccount;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.GlVoucher;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.accounting.journalentry.service.GlVoucherWriteService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class AccountingOperationsCutoffTest {

    private static final LocalDate HISTORICAL_DATE = LocalDate.of(2026, 9, 30);

    private final AccountingProcessorHelper accountingProcessorHelper = mock(AccountingProcessorHelper.class);
    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository = mock(
            FinancialActivityAccountRepositoryWrapper.class);
    private final AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);
    private final GlVoucherWriteService glVoucherWriteService = mock(GlVoucherWriteService.class);

    @BeforeEach
    void setBusinessDate() {
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, HISTORICAL_DATE)));
    }

    @AfterEach
    void clearBusinessDate() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void suppressesEveryAvailableAtCashierJournalGroupBeforeResolvingAccounts() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(false);
        AvailableAtCashierAccountingHelper helper = new AvailableAtCashierAccountingHelper(accountingProcessorHelper,
                financialActivityAccountRepository, cutoffPolicyService, glVoucherWriteService);
        SesionComite session = mock(SesionComite.class);
        List<Loan> loans = List.of(mock(Loan.class));

        helper.vaultReceptionFromBank(session, loans, HISTORICAL_DATE);
        helper.cashierCashReception(session, loans, HISTORICAL_DATE);
        helper.disbursementPayableClearing(session, loans, HISTORICAL_DATE);

        verifyNoInteractions(accountingProcessorHelper, financialActivityAccountRepository, glVoucherWriteService);
    }

    @Test
    void suppressesBothVaultTransferDirectionsBeforeResolvingAccounts() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(false);
        TellerVaultTransferAccountingHelper helper = new TellerVaultTransferAccountingHelper(financialActivityAccountRepository,
                accountingProcessorHelper, cutoffPolicyService, glVoucherWriteService);

        helper.postVaultTransferFromTeller(mock(Office.class), BigDecimal.ONE, "USD", HISTORICAL_DATE, "from", null);
        helper.postVaultTransferToTeller(mock(Office.class), BigDecimal.ONE, "USD", HISTORICAL_DATE, "to", null);

        verifyNoInteractions(accountingProcessorHelper, financialActivityAccountRepository, glVoucherWriteService);
    }

    @Test
    void tellerToVaultPostsOneVoucherForBothBalancedLines() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(true);
        GLAccount vaultAccount = mock(GLAccount.class);
        GLAccount tellerAccount = mock(GLAccount.class);
        FinancialActivityAccount vaultActivity = mock(FinancialActivityAccount.class);
        FinancialActivityAccount tellerActivity = mock(FinancialActivityAccount.class);
        when(vaultActivity.getGlAccount()).thenReturn(vaultAccount);
        when(tellerActivity.getGlAccount()).thenReturn(tellerAccount);
        when(financialActivityAccountRepository.findByFinancialActivityTypeWithNotFoundDetection(
                FinancialActivity.CASH_AT_MAINVAULT.getValue())).thenReturn(vaultActivity);
        when(financialActivityAccountRepository.findByFinancialActivityTypeWithNotFoundDetection(
                FinancialActivity.CASH_AT_TELLER.getValue())).thenReturn(tellerActivity);
        GlVoucher voucher = GlVoucher.create("20", "Transferencia de caja a bóveda", "NATIVE_OPERATION", "TELLER_TO_VAULT",
                "TELLER_VAULT_TRANSFER", "transfer-1", null);
        when(glVoucherWriteService.createNative("TELLER_TO_VAULT", "Transferencia de caja a bóveda",
                "TELLER_VAULT_TRANSFER", "transfer-1")).thenReturn(voucher);
        TellerVaultTransferAccountingHelper helper = new TellerVaultTransferAccountingHelper(financialActivityAccountRepository,
                accountingProcessorHelper, cutoffPolicyService, glVoucherWriteService);

        helper.postVaultTransferFromTeller(mock(Office.class), BigDecimal.TEN, "USD", HISTORICAL_DATE, "transfer-1", "note");

        ArgumentCaptor<JournalEntry> entries = ArgumentCaptor.forClass(JournalEntry.class);
        verify(accountingProcessorHelper, times(2)).persistJournalEntry(entries.capture());
        assertThat(entries.getAllValues()).hasSize(2).allSatisfy(entry -> {
            assertThat(entry.getVoucher()).isSameAs(voucher);
            assertThat(entry.getAmount()).isEqualByComparingTo(BigDecimal.TEN);
        });
        assertThat(entries.getAllValues().get(0).isDebitEntry()).isTrue();
        assertThat(entries.getAllValues().get(0).getGlAccount()).isSameAs(vaultAccount);
        assertThat(entries.getAllValues().get(1).isDebitEntry()).isFalse();
        assertThat(entries.getAllValues().get(1).getGlAccount()).isSameAs(tellerAccount);
    }

    @Test
    void committeeDisbursementClearingKeepsMultipleLoansInOneVoucher() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(true);
        SesionComite session = mock(SesionComite.class);
        when(session.getId()).thenReturn(88L);
        Office office = mock(Office.class);
        Loan firstLoan = mock(Loan.class);
        Loan secondLoan = mock(Loan.class);
        when(firstLoan.getNetDisbursalAmount()).thenReturn(new BigDecimal("4.00"));
        when(secondLoan.getNetDisbursalAmount()).thenReturn(new BigDecimal("6.00"));
        when(firstLoan.getOffice()).thenReturn(office);
        when(firstLoan.getCurrencyCode()).thenReturn("USD");
        when(firstLoan.getId()).thenReturn(1L);
        when(secondLoan.getId()).thenReturn(2L);
        for (FinancialActivity activity : List.of(FinancialActivity.CASH_AT_MAINVAULT, FinancialActivity.CASH_AT_TELLER,
                FinancialActivity.DISBURSEMENTS_PAYABLE)) {
            FinancialActivityAccount account = mock(FinancialActivityAccount.class);
            when(account.getGlAccount()).thenReturn(mock(GLAccount.class));
            when(financialActivityAccountRepository.findByFinancialActivityTypeWithNotFoundDetection(activity.getValue()))
                    .thenReturn(account);
        }
        GlVoucher voucher = GlVoucher.create("4", "Liquidación de desembolsos de comité", "NATIVE_OPERATION",
                "COMITE_DISBURSEMENT_CLEARING", "COMITE_SESSION", "88", null);
        when(glVoucherWriteService.createNative("COMITE_DISBURSEMENT_CLEARING",
                "Liquidación de desembolsos de comité", "COMITE_SESSION", "88")).thenReturn(voucher);
        AvailableAtCashierAccountingHelper helper = new AvailableAtCashierAccountingHelper(accountingProcessorHelper,
                financialActivityAccountRepository, cutoffPolicyService, glVoucherWriteService);

        helper.disbursementPayableClearing(session, List.of(firstLoan, secondLoan), HISTORICAL_DATE);

        ArgumentCaptor<JournalEntry> entries = ArgumentCaptor.forClass(JournalEntry.class);
        verify(accountingProcessorHelper, times(3)).persistJournalEntry(entries.capture());
        assertThat(entries.getAllValues()).allSatisfy(entry -> assertThat(entry.getVoucher()).isSameAs(voucher));
        assertThat(entries.getAllValues().get(0).isCreditEntry()).isTrue();
        assertThat(entries.getAllValues().get(0).getAmount()).isEqualByComparingTo("10.00");
        assertThat(entries.getAllValues().subList(1, 3)).allSatisfy(entry -> assertThat(entry.isDebitEntry()).isTrue());
        assertThat(entries.getAllValues().get(1).getAmount()).isEqualByComparingTo("4.00");
        assertThat(entries.getAllValues().get(2).getAmount()).isEqualByComparingTo("6.00");
    }
}
