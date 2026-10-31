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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.journalentry.domain.GlVoucherRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.accounting.journalentry.service.GlVoucherWriteService;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingCashMovementRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingOperation;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingOperationRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Answers;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

class LoanRefinancingOperationServiceTest {

    @Mock
    LoanRefinancingOperationRepository operations;
    @Mock
    LoanRefinancingCashMovementRepository movements;
    @Mock
    LoanRepository loans;
    @Mock
    org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository transactions;
    @Mock
    JournalEntryRepository journals;
    @Mock
    GlVoucherRepository vouchers;
    @Mock
    GlVoucherWriteService voucherWriter;
    @Mock
    JournalEntryPersistenceService persistence;
    @Mock
    AccountingProcessorHelper helper;
    @Mock
    AccountingCutoffPolicyService cutoff;
    @Mock(answer = Answers.RETURNS_DEEP_STUBS)
    PlatformSecurityContext security;
    @InjectMocks
    LoanRefinancingOperationService service;
    @Mock(answer = Answers.RETURNS_DEEP_STUBS)
    Loan successor;
    @Mock
    Loan predecessor;
    AutoCloseable mocks;
    LoanRefinancingOperation op;
    LocalDate date = LocalDate.of(2026, 10, 30);

    @BeforeEach
    void setup() {
        mocks = MockitoAnnotations.openMocks(this);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, date)));
        op = new LoanRefinancingOperation();
        op.setLoanId(10L);
        op.setOfficeId(1L);
        op.setOperationDate(date);
        op.setCurrencyCode("USD");
        op.setProceedsMode("CASH");
        op.setPayoutEntitlement(new BigDecimal("238.99"));
        op.getTransactionIds().addAll(Set.of(100L, 101L));
        when(successor.getId()).thenReturn(10L);
        when(successor.getClientId()).thenReturn(5L);
        when(successor.getOffice().getHierarchy()).thenReturn(".1.");
        when(security.authenticatedUser().getOffice().getHierarchy()).thenReturn(".1.");
        when(successor.getTopupLoanDetails().getLoanIdsToClose()).thenReturn(List.of(9L));
        when(successor.getTopupLoanDetails().getSettlements()).thenReturn(List.of());
        when(successor.getLoanTransactions()).thenReturn(List.of());
        when(predecessor.getLoanTransactions()).thenReturn(List.of());
        var office = successor.getOffice();
        when(predecessor.getOffice()).thenReturn(office);
        when(loans.findById(10L)).thenReturn(Optional.of(successor));
        when(loans.findById(9L)).thenReturn(Optional.of(predecessor));
        when(loans.findAllByIdForRefinancingUpdate(List.of(9L, 10L))).thenReturn(List.of(predecessor, successor));
        when(operations.findFirstByLoanIdOrderByIdDesc(10L)).thenReturn(Optional.of(op));
        when(movements.findByOperationIdOrderByIdAsc(any())).thenReturn(List.of());
    }

    @AfterEach
    void cleanup() throws Exception {
        ThreadLocalContextUtil.reset();
        mocks.close();
    }

    @Test
    void undeliveredCashDoesNotRequireFictitiousReturn() {
        var preview = service.read(10L);
        assertEquals(true, preview.get("canReverse"));
        assertEquals(BigDecimal.ZERO, preview.get("outstandingCash"));
    }

    @Test
    void partialDeliveryRequiresOnlyActuallyDeliveredCash() {
        op.setDeliveredAmount(new BigDecimal("100"));
        op.setReturnedAmount(new BigDecimal("30"));
        var preview = service.read(10L);
        assertEquals(false, preview.get("canReverse"));
        assertEquals(new BigDecimal("70"), preview.get("outstandingCash"));
        assertEquals(List.of("cash.return.required"), preview.get("blockers"));
    }

    @Test
    void fullReturnAllowsUnwindWithoutReturningUndeliveredBalance() {
        op.setDeliveredAmount(new BigDecimal("100"));
        op.setReturnedAmount(new BigDecimal("100"));
        assertSame(op, service.prepareUndo(successor, date));
    }

    @Test
    void laterOrdinaryRepaymentBlocksWithoutMutatingEitherLoan() {
        LoanTransaction owned = mock(LoanTransaction.class), later = mock(LoanTransaction.class);
        when(owned.getId()).thenReturn(100L);
        when(later.getId()).thenReturn(200L);
        when(successor.getLoanTransactions()).thenReturn(List.of(owned, later));
        when(successor.isUserTransaction(later)).thenReturn(true);
        assertThrows(RuntimeException.class, () -> service.prepareUndo(successor, date));
        verifyNoInteractions(persistence, voucherWriter);
    }

    @Test
    void operationIsReadAfterRelatedLoansAreLocked() {
        service.prepareUndo(successor, date);
        var order = inOrder(loans, operations);
        order.verify(loans).findAllByIdForRefinancingUpdate(List.of(9L, 10L));
        order.verify(operations).findFirstByLoanIdOrderByIdDesc(10L);
    }

    @Test
    void alreadyReversedIsIdempotent() {
        op.setReversed(true);
        assertSame(op, service.prepareUndo(successor, date));
        verifyNoInteractions(cutoff, journals, persistence);
    }

    @Test
    void closedAccountingBoundaryLeavesFinancialStateUnchanged() {
        doThrow(new IllegalStateException("closed")).when(cutoff).assertJournalPersistenceAllowed(date);
        assertThrows(IllegalStateException.class, () -> service.prepareUndo(successor, date));
        verifyNoInteractions(persistence, voucherWriter);
        assertFalse(op.isReversed());
    }

    @Test void legacyUnknownProvenanceIsNotGuessed() {
        when(operations.findFirstByLoanIdOrderByIdDesc(10L)).thenReturn(Optional.empty());
        assertThrows(RuntimeException.class, () -> service.prepareUndo(successor,date)); verifyNoInteractions(persistence,journals);
    }

    @Test
    void recordedCashMustBeReturnedBeforeUndoCanBegin() {
        op.setDeliveredAmount(new BigDecimal("20"));
        assertThrows(RuntimeException.class, () -> service.prepareUndo(successor, date));
        verifyNoInteractions(persistence, voucherWriter);
    }

    @Test void blocksIndependentAdjustmentOfAnOwnedRefinanceTransaction() {
        when(operations.countActiveOwners(100L)).thenReturn(1L);
        assertThrows(RuntimeException.class, () -> service.assertIndependentAdjustmentAllowed(100L));
        service.assertIndependentAdjustmentAllowed(999L);
        verifyNoInteractions(persistence,voucherWriter);
    }

    @Test
    void reviewShowsTheActualPredecessorPaymentComponents() {
        var settlement = mock(org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingSettlement.class);
        var payoff = mock(LoanTransaction.class);
        when(settlement.getLoanIdToClose()).thenReturn(9L);
        when(settlement.getRepaymentTransactionId()).thenReturn(200L);
        when(settlement.getSettlementAmount()).thenReturn(new BigDecimal("10.00"));
        when(successor.getTopupLoanDetails().getSettlements()).thenReturn(List.of(settlement));
        when(transactions.findById(200L)).thenReturn(Optional.of(payoff));
        when(payoff.getPrincipalPortion()).thenReturn(new BigDecimal("9.00"));
        when(payoff.getInterestPortion()).thenReturn(new BigDecimal("0.50"));
        when(payoff.getFeeChargesPortion()).thenReturn(new BigDecimal("0.40"));
        when(payoff.getPenaltyChargesPortion()).thenReturn(new BigDecimal("0.10"));
        var preview = service.read(10L);
        var components = (Map<?, ?>) ((List<?>) preview.get("predecessors")).getFirst();
        assertEquals(new BigDecimal("9.00"), components.get("principal"));
        assertEquals(new BigDecimal("0.50"), components.get("interest"));
        assertEquals(new BigDecimal("0.40"), components.get("fees"));
        assertEquals(new BigDecimal("0.10"), components.get("penalties"));
    }

}
