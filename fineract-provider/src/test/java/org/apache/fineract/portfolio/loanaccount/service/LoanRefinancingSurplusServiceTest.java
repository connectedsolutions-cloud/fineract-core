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
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.same;
import static org.mockito.Mockito.RETURNS_DEEP_STUBS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.account.PortfolioAccountType;
import org.apache.fineract.portfolio.account.data.AccountTransferDTO;
import org.apache.fineract.portfolio.account.domain.AccountTransferAssembler;
import org.apache.fineract.portfolio.account.domain.AccountTransferDetailRepository;
import org.apache.fineract.portfolio.account.domain.AccountTransferDetails;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanAccountDomainService;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionType;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class LoanRefinancingSurplusServiceTest {

    private static final LocalDate DATE = LocalDate.of(2026, 10, 20);
    private final MonetaryCurrency currency = new MonetaryCurrency("USD", 2, 0);
    private final Loan loan = mock(Loan.class, RETURNS_DEEP_STUBS);
    private final LoanAccountDomainService domain = mock(LoanAccountDomainService.class);
    private final LoanTransactionRepository transactions = mock(LoanTransactionRepository.class);
    private final LoanJournalEntryPoster journals = mock(LoanJournalEntryPoster.class);
    private final AccountTransferAssembler assembler = mock(AccountTransferAssembler.class);
    private final AccountTransferDetailRepository transfers = mock(AccountTransferDetailRepository.class);
    private final LoanRefinancingSurplusService service = new LoanRefinancingSurplusService(domain, transactions, journals, assembler,
            transfers);

    @BeforeEach
    void setup() {
        ThreadLocalContextUtil
                .setTenant(new FineractPlatformTenant(1L, "refinancing-surplus-test", "Synthetic", "America/El_Salvador", null));
        MoneyHelper.initializeTenantRoundingMode("refinancing-surplus-test", 6);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, DATE)));
        when(loan.isTopup()).thenReturn(true);
        when(loan.getClientId()).thenReturn(1L);
        when(loan.getId()).thenReturn(42L);
        when(loan.getActiveCharges()).thenReturn(Set.of());
        when(loan.getCurrency()).thenReturn(currency);
        when(loan.getTotalOverpaidAsMoney()).thenReturn(Money.zero(currency));
    }

    @AfterEach
    void cleanup() {
        MoneyHelper.clearCacheForTenant("refinancing-surplus-test");
        ThreadLocalContextUtil.reset();
    }

    @Test
    void retainsOnlyNetProceedsAfterPayoffAndFees() {
        assertEquals(new BigDecimal("2900.00"), service.repaymentAmount(money("3000"), new BigDecimal("100")).getAmount());
        assertEquals(new BigDecimal("3000.00"), service.repaymentAmount(money("3000"), BigDecimal.ZERO).getAmount());
    }

    @Test
    void zeroSurplusDoesNotCreateAnyTransactions() {
        assertEquals(BigDecimal.ZERO.setScale(2), service.repaymentAmount(money("100"), new BigDecimal("100")).getAmount());
        assertNull(service.createDisbursement(loan, money("0"), DATE, ExternalId.empty()));
        assertNull(service.applyRepayment(loan, null, money("0"), DATE, Locale.US, DateTimeFormatter.ISO_DATE));
        verifyNoInteractions(domain, transactions, journals, assembler, transfers);
    }

    @Test
    void rejectsChargesLargerThanRemainder() {
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.repaymentAmount(money("99"), new BigDecimal("100")));
    }

    @Test
    void createsInternalDisbursementWithoutCashPaymentDetail() {
        final LoanTransaction result = service.createDisbursement(loan, money("3000"), DATE, ExternalId.empty());
        assertSame(loan, result.getLoan());
        assertNull(result.getPaymentDetail());
        assertEquals(money("3000").getAmount(), result.getAmount(currency).getAmount());
        verify(loan).addLoanTransaction(result);
        verify(transactions).saveAndFlush(result);
        verify(journals).postJournalEntriesForLoanTransaction(result, true, true);
        verifyNoInteractions(domain, assembler, transfers);
    }

    @Test
    void repaysThroughNativeAllocationAndPersistsLinkedSameLoanTransfer() {
        final LoanTransaction disbursement = mock(LoanTransaction.class);
        when(disbursement.getExternalId()).thenReturn(ExternalId.empty());
        final LoanTransaction repayment = mock(LoanTransaction.class);
        when(domain.makeRepayment(eq(LoanTransactionType.REPAYMENT), same(loan), eq(DATE), eq(money("2900").getAmount()), isNull(),
                eq("Refinancing surplus repayment"), any(ExternalId.class), eq(false), isNull(), eq(true), isNull(), eq(false), eq(true)))
                .thenReturn(repayment);
        final AccountTransferDetails details = mock(AccountTransferDetails.class);
        when(assembler.assembleLoanToLoanTransfer(any(), same(loan), same(loan), same(disbursement), same(repayment))).thenReturn(details);
        assertSame(repayment, service.applyRepayment(loan, disbursement, money("2900"), DATE, Locale.US, DateTimeFormatter.ISO_DATE));
        final ArgumentCaptor<AccountTransferDTO> transfer = ArgumentCaptor.forClass(AccountTransferDTO.class);
        verify(assembler).assembleLoanToLoanTransfer(transfer.capture(), same(loan), same(loan), same(disbursement), same(repayment));
        assertEquals(42L, transfer.getValue().getFromAccountId());
        assertEquals(42L, transfer.getValue().getToAccountId());
        assertEquals(PortfolioAccountType.LOAN, transfer.getValue().getFromAccountType());
        assertEquals(PortfolioAccountType.LOAN, transfer.getValue().getToAccountType());
        assertEquals(DATE, transfer.getValue().getTransactionDate());
        verify(transfers).saveAndFlush(details);
    }

    @Test
    void supportsOrdinarySingleLoanRefinanceAndConsolidation() {
        assertTrue(LoanRefinancingSurplusService.isEligible(loan));
        assertDoesNotThrow(() -> service.validateRequest(loan, true, false));
    }

    @Test
    void leavesUnselectedFlowsUnchanged() {
        when(loan.isTopup()).thenReturn(false);
        assertDoesNotThrow(() -> service.validateRequest(loan, false, false));
        assertDoesNotThrow(() -> service.validateRequest(loan, false, true));
    }

    @Test
    void rejectsOrdinaryLoansAndSourceExactMigrationCommands() {
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.validateRequest(loan, true, true));
        when(loan.isTopup()).thenReturn(false);
        assertFalse(LoanRefinancingSurplusService.isEligible(loan));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.validateRequest(loan, true, false));
    }

    @Test
    void rejectsMultiDisbursementAndDownPaymentProducts() {
        when(loan.isMultiDisburmentLoan()).thenReturn(true);
        assertFalse(LoanRefinancingSurplusService.isEligible(loan));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.validateRequest(loan, true, false));
        when(loan.isMultiDisburmentLoan()).thenReturn(false);
        when(loan.getLoanProductRelatedDetail().isEnableDownPayment()).thenReturn(true);
        assertFalse(LoanRefinancingSurplusService.isEligible(loan));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.validateRequest(loan, true, false));
    }

    @Test
    void rejectsSavingsPaidDisbursementCharges() {
        final LoanCharge charge = mock(LoanCharge.class, RETURNS_DEEP_STUBS);
        when(charge.isDueAtDisbursement()).thenReturn(true);
        when(charge.getChargePaymentMode().isPaymentModeAccountTransfer()).thenReturn(true);
        when(loan.getActiveCharges()).thenReturn(Set.of(charge));
        assertFalse(LoanRefinancingSurplusService.isEligible(loan));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.validateRequest(loan, true, false));
    }

    private Money money(final String amount) {
        return Money.of(currency, new BigDecimal(amount));
    }
}
