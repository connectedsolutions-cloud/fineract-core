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

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.Optional;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.service.CurrencyReadPlatformService;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.organisation.teller.data.CashierTransactionDataValidator;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.organisation.teller.domain.TellerRepositoryWrapper;
import org.apache.fineract.organisation.teller.serialization.TellerCommandFromApiJsonDeserializer;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;

class TellerWritePlatformServiceCutoffTest {

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
                mock(TellerCommandFromApiJsonDeserializer.class), mock(TellerRepositoryWrapper.class),
                mock(OfficeRepositoryWrapper.class), mock(StaffRepository.class), cashierRepository, cashierTransactionRepository,
                journalEntryPersistenceService, cutoffPolicyService, financialActivityAccountRepository,
                mock(CashierTransactionDataValidator.class), mock(CurrencyReadPlatformService.class));

        try (MockedStatic<CashierTransaction> transactions = mockStatic(CashierTransaction.class)) {
            transactions.when(() -> CashierTransaction.fromJson(cashier, command)).thenReturn(transaction);
            service.allocateCashToCashier(7L, command);
        }

        verify(cashierTransactionRepository).save(transaction);
        verifyNoInteractions(journalEntryPersistenceService, financialActivityAccountRepository);
    }
}
