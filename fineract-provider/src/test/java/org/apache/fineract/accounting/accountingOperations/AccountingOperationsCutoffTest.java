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

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.junit.jupiter.api.Test;

class AccountingOperationsCutoffTest {

    private static final LocalDate HISTORICAL_DATE = LocalDate.of(2026, 9, 30);

    private final AccountingProcessorHelper accountingProcessorHelper = mock(AccountingProcessorHelper.class);
    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository = mock(
            FinancialActivityAccountRepositoryWrapper.class);
    private final AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);

    @Test
    void suppressesEveryAvailableAtCashierJournalGroupBeforeResolvingAccounts() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(false);
        AvailableAtCashierAccountingHelper helper = new AvailableAtCashierAccountingHelper(accountingProcessorHelper,
                financialActivityAccountRepository, cutoffPolicyService);
        SesionComite session = mock(SesionComite.class);
        List<Loan> loans = List.of(mock(Loan.class));

        helper.vaultReceptionFromBank(session, loans, HISTORICAL_DATE);
        helper.cashierCashReception(session, loans, HISTORICAL_DATE);
        helper.disbursementPayableClearing(session, loans, HISTORICAL_DATE);

        verifyNoInteractions(accountingProcessorHelper, financialActivityAccountRepository);
    }

    @Test
    void suppressesBothVaultTransferDirectionsBeforeResolvingAccounts() {
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(false);
        TellerVaultTransferAccountingHelper helper = new TellerVaultTransferAccountingHelper(financialActivityAccountRepository,
                accountingProcessorHelper, cutoffPolicyService);

        helper.postVaultTransferFromTeller(mock(Office.class), BigDecimal.ONE, "USD", HISTORICAL_DATE, "from", null);
        helper.postVaultTransferToTeller(mock(Office.class), BigDecimal.ONE, "USD", HISTORICAL_DATE, "to", null);

        verifyNoInteractions(accountingProcessorHelper, financialActivityAccountRepository);
    }
}
