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
package org.apache.fineract.portfolio.transfer.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.google.gson.JsonObject;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanSummary;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.junit.jupiter.api.Test;

class DeferredSourceClosedLoanTransferTest {
    @Test
    void requiresOffPolicyExactPayoffPaidPrincipalAndNoLaterNativeActivity() {
        Loan loan = mock(Loan.class);
        LoanSummary summary = mock(LoanSummary.class);
        LoanTransaction payoff = mock(LoanTransaction.class);
        when(loan.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD:1"));
        when(loan.getSummary()).thenReturn(summary);
        when(summary.getTotalPrincipalOutstanding()).thenReturn(BigDecimal.ZERO);
        when(loan.getLoanTransactions()).thenReturn(List.of(payoff));
        when(payoff.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD-MOV:1"));
        when(payoff.getTransactionDate()).thenReturn(LocalDate.of(2024, 10, 16));
        when(payoff.isRepayment()).thenReturn(true);
        JsonObject proof = new JsonObject();
        proof.addProperty("loanExternalId", "ARISSTO:CRD:1");
        proof.addProperty("terminalExternalId", "ARISSTO:CRD-MOV:1");
        proof.addProperty("terminalDate", "2024-10-16");
        LocalDate transfer = LocalDate.of(2024, 11, 27);
        assertDoesNotThrow(() -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
        when(loan.isInterestRecalculationEnabled()).thenReturn(true);
        assertThrows(IllegalArgumentException.class,
                () -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
        when(loan.isInterestRecalculationEnabled()).thenReturn(false);
        when(summary.getTotalPrincipalOutstanding()).thenReturn(new BigDecimal("1.00"));
        assertThrows(IllegalArgumentException.class,
                () -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
        when(summary.getTotalPrincipalOutstanding()).thenReturn(BigDecimal.ZERO);
        when(payoff.isReversed()).thenReturn(true);
        assertThrows(IllegalArgumentException.class,
                () -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
        when(payoff.isReversed()).thenReturn(false);
        when(payoff.getTransactionDate()).thenReturn(transfer);
        assertThrows(IllegalArgumentException.class,
                () -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
        when(payoff.getTransactionDate()).thenReturn(transfer.minusDays(1));
        assertThrows(IllegalArgumentException.class,
                () -> TransferWritePlatformServiceJpaRepositoryImpl.validateDeferredSourceClosedLoan(loan, proof, transfer));
    }
}
