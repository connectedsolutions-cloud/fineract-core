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
package org.apache.fineract.portfolio.account.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.portfolio.account.domain.AccountTransferRepository;
import org.apache.fineract.portfolio.account.domain.AccountTransferTransaction;
import org.apache.fineract.portfolio.account.domain.AccountTransferDetails;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransaction;
import org.apache.fineract.portfolio.savings.service.SavingsAccountWritePlatformService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AccountTransfersWritePlatformServiceImplTest {

    @Mock
    private AccountTransferRepository accountTransferRepository;

    @Mock
    private SavingsAccountWritePlatformService savingsAccountWritePlatformService;

    @InjectMocks
    private AccountTransfersWritePlatformServiceImpl service;

    @Test
    void shouldUndoUntransferredFixedDepositInterestPosting() {
        final long savingsAccountId = 83L;
        final long transactionId = 12210L;
        final LocalDate transactionDate = LocalDate.of(2026, 8, 30);
        final BigDecimal amount = new BigDecimal("10.25");
        when(accountTransferRepository.findActiveByFromSavingsAccountDateAndAmount(savingsAccountId, transactionDate, amount))
                .thenReturn(List.of());

        final boolean reversed = service.reverseUniqueSavingsTransferAndInterestPosting(savingsAccountId, transactionId, transactionDate,
                amount, true);

        assertThat(reversed).isTrue();
        verify(savingsAccountWritePlatformService).undoTransaction(savingsAccountId, transactionId, true, true);
    }

    @Test
    void shouldReverseOneTransferByExactSourceTransaction() {
        final long savingsAccountId = 36L;
        final long transactionId = 12175L;
        final AccountTransferTransaction transfer = org.mockito.Mockito.mock(AccountTransferTransaction.class);
        final AccountTransferDetails details = org.mockito.Mockito.mock(AccountTransferDetails.class);
        final SavingsAccount account = org.mockito.Mockito.mock(SavingsAccount.class);
        final SavingsAccountTransaction fromTransaction = org.mockito.Mockito.mock(SavingsAccountTransaction.class);
        when(account.getId()).thenReturn(savingsAccountId);
        when(fromTransaction.getId()).thenReturn(transactionId);
        when(details.fromSavingsAccount()).thenReturn(account);
        when(transfer.accountTransferDetails()).thenReturn(details);
        when(transfer.getFromTransaction()).thenReturn(fromTransaction);
        when(accountTransferRepository.findByFromSavingsTransactions(List.of(transactionId))).thenReturn(List.of(transfer));

        assertThat(service.reverseUniqueSavingsTransfer(savingsAccountId, transactionId)).isTrue();

        verify(savingsAccountWritePlatformService).undoTransaction(savingsAccountId, transactionId, true);
        verify(transfer).reverse();
        verify(accountTransferRepository).save(transfer);
    }
}
