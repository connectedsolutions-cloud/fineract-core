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
package org.apache.fineract.organisation.teller.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccount;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.GlVoucher;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.service.GlVoucherWriteService;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.service.CurrencyReadPlatformService;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.organisation.teller.data.CashierTransactionDataValidator;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.organisation.teller.domain.Teller;
import org.apache.fineract.organisation.teller.domain.TellerRepositoryWrapper;
import org.apache.fineract.organisation.teller.serialization.TellerCommandFromApiJsonDeserializer;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

class TellerWritePlatformServiceCutoffTest {

    @AfterEach
    void clearBusinessDate() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void migrationSuppressionRetainsCashierTransactionAndSkipsOnlyItsJournalPair() {
        LocalDate historicalDate = LocalDate.of(2026, 9, 30);
        CashierRepository cashierRepository = mock(CashierRepository.class);
        CashierTransactionRepository cashierTransactionRepository = mock(CashierTransactionRepository.class);
        JournalEntryPersistenceService journalEntryPersistenceService = mock(JournalEntryPersistenceService.class);
        AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);
        FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository = mock(
                FinancialActivityAccountRepositoryWrapper.class);
        Cashier cashier = mock(Cashier.class);
        CashierTransaction transaction = mock(CashierTransaction.class);
        JsonCommand command = mock(JsonCommand.class);
        when(cashierRepository.findById(7L)).thenReturn(Optional.of(cashier));
        when(transaction.getTxnDate()).thenReturn(historicalDate);
        when(cutoffPolicyService.shouldGenerateAccounting(historicalDate)).thenReturn(false);

        TellerWritePlatformServiceJpaImpl service = new TellerWritePlatformServiceJpaImpl(mock(PlatformSecurityContext.class),
                mock(TellerCommandFromApiJsonDeserializer.class), mock(TellerRepositoryWrapper.class), mock(OfficeRepositoryWrapper.class),
                mock(StaffRepository.class), cashierRepository, cashierTransactionRepository, journalEntryPersistenceService,
                cutoffPolicyService, financialActivityAccountRepository, mock(CashierTransactionDataValidator.class),
                mock(CurrencyReadPlatformService.class), mock(GlVoucherWriteService.class));

        try (MockedStatic<CashierTransaction> transactions = mockStatic(CashierTransaction.class)) {
            transactions.when(() -> CashierTransaction.fromJson(cashier, command)).thenReturn(transaction);
            service.allocateCashToCashier(7L, command);
        }

        verify(cashierTransactionRepository).save(transaction);
        verifyNoInteractions(journalEntryPersistenceService, financialActivityAccountRepository);
    }

    @Test
    void cashierAllocationLinksBothPostedLinesToOneVoucher() {
        LocalDate businessDate = LocalDate.of(2026, 10, 12);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, businessDate)));
        CashierRepository cashierRepository = mock(CashierRepository.class);
        CashierTransactionRepository cashierTransactionRepository = mock(CashierTransactionRepository.class);
        JournalEntryPersistenceService journalEntryPersistenceService = mock(JournalEntryPersistenceService.class);
        AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);
        FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository = mock(
                FinancialActivityAccountRepositoryWrapper.class);
        GlVoucherWriteService glVoucherWriteService = mock(GlVoucherWriteService.class);
        PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
        AppUser user = mock(AppUser.class);
        when(securityContext.authenticatedUser()).thenReturn(user);
        when(user.getId()).thenReturn(9L);
        Cashier cashier = mock(Cashier.class);
        Teller teller = mock(Teller.class);
        Office office = mock(Office.class);
        when(cashier.getTeller()).thenReturn(teller);
        when(teller.getOffice()).thenReturn(office);
        when(office.getId()).thenReturn(3L);
        when(cashierRepository.findById(7L)).thenReturn(Optional.of(cashier));
        CashierTransaction transaction = mock(CashierTransaction.class);
        when(transaction.getId()).thenReturn(41L);
        when(transaction.getTxnDate()).thenReturn(businessDate);
        when(transaction.getTxnAmount()).thenReturn(BigDecimal.TEN);
        when(transaction.getCurrencyCode()).thenReturn("USD");
        when(cutoffPolicyService.shouldGenerateAccounting(businessDate)).thenReturn(true);
        GLAccount vaultAccount = mock(GLAccount.class);
        GLAccount tellerAccount = mock(GLAccount.class);
        FinancialActivityAccount vaultActivity = mock(FinancialActivityAccount.class);
        FinancialActivityAccount tellerActivity = mock(FinancialActivityAccount.class);
        when(vaultActivity.getGlAccount()).thenReturn(vaultAccount);
        when(tellerActivity.getGlAccount()).thenReturn(tellerAccount);
        when(financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_MAINVAULT.getValue()))
                .thenReturn(vaultActivity);
        when(financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_TELLER.getValue())).thenReturn(tellerActivity);
        GlVoucher voucher = GlVoucher.create("3", "Asignación de efectivo a caja", "NATIVE_OPERATION", "TELLER_ALLOCATE",
                "CASHIER_TRANSACTION", "41", null);
        when(glVoucherWriteService.createNative("TELLER_ALLOCATE", "Asignación de efectivo a caja", "CASHIER_TRANSACTION", "41"))
                .thenReturn(voucher);
        JsonCommand command = mock(JsonCommand.class);
        TellerWritePlatformServiceJpaImpl service = new TellerWritePlatformServiceJpaImpl(securityContext,
                mock(TellerCommandFromApiJsonDeserializer.class), mock(TellerRepositoryWrapper.class), mock(OfficeRepositoryWrapper.class),
                mock(StaffRepository.class), cashierRepository, cashierTransactionRepository, journalEntryPersistenceService,
                cutoffPolicyService, financialActivityAccountRepository, mock(CashierTransactionDataValidator.class),
                mock(CurrencyReadPlatformService.class), glVoucherWriteService);

        try (MockedStatic<CashierTransaction> transactions = mockStatic(CashierTransaction.class)) {
            transactions.when(() -> CashierTransaction.fromJson(cashier, command)).thenReturn(transaction);
            service.allocateCashToCashier(7L, command);
        }

        ArgumentCaptor<JournalEntry> entries = ArgumentCaptor.forClass(JournalEntry.class);
        verify(journalEntryPersistenceService, times(2)).saveAndFlush(entries.capture());
        assertThat(entries.getAllValues()).hasSize(2).allSatisfy(entry -> {
            assertThat(entry.getVoucher()).isSameAs(voucher);
            assertThat(entry.getAmount()).isEqualByComparingTo(BigDecimal.TEN);
        });
        assertThat(entries.getAllValues().get(0).isDebitEntry()).isTrue();
        assertThat(entries.getAllValues().get(0).getGlAccount()).isSameAs(tellerAccount);
        assertThat(entries.getAllValues().get(1).isCreditEntry()).isTrue();
        assertThat(entries.getAllValues().get(1).getGlAccount()).isSameAs(vaultAccount);
    }
}
