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
package org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.MockedStatic;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
public class CredesalPenaltiesFeesInterestPrincipalLoanRepaymentScheduleTransactionProcessorTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static final MockedStatic<MoneyHelper> MONEY_HELPER = Mockito.mockStatic(MoneyHelper.class);

    private CredesalPenaltiesFeesInterestPrincipalLoanRepaymentScheduleTransactionProcessor underTest;
    private Office office;
    private Loan loan;
    private LocalDate transactionDate;

    @BeforeAll
    public static void init() {
        MONEY_HELPER.when(MoneyHelper::getMathContext).thenReturn(new MathContext(12, RoundingMode.HALF_EVEN));
        MONEY_HELPER.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
    }

    @AfterAll
    public static void destruct() {
        MONEY_HELPER.close();
    }

    @BeforeEach
    public void setUp() {
        underTest = new CredesalPenaltiesFeesInterestPrincipalLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class));
        office = mock(Office.class);
        loan = mock(Loan.class);
        transactionDate = LocalDate.of(2026, 2, 10);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "Asia/Kolkata", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, transactionDate)));
    }

    @AfterEach
    public void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    public void paymentEqualToTotalPenaltiesClearsOnlyPenaltiesAcrossInstallments() {
        final List<LoanRepaymentScheduleInstallment> installments = twoOverdueInstallments();
        final Money payment = Money.of(CURRENCY, BigDecimal.valueOf(20)); // 10 + 10 penalties
        final LoanTransaction loanTransaction = LoanTransaction.repayment(office, payment, null, transactionDate, ExternalId.empty());

        final Money remaining = underTest.processTransaction(loanTransaction, CURRENCY, installments, new HashSet<>(), null);

        assertEquals(0, remaining.getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, loanTransaction.getPenaltyChargesPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(20)));
        assertEquals(0, loanTransaction.getInterestPortion(CURRENCY).getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, loanTransaction.getPrincipalPortion(CURRENCY).getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, installments.get(0).getPenaltyChargesOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, installments.get(1).getPenaltyChargesOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, installments.get(0).getInterestOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(5)));
        assertEquals(0, installments.get(1).getInterestOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(5)));
        assertEquals(0, installments.get(0).getPrincipalOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(100)));
    }

    @Test
    public void paymentEqualToPenaltiesPlusInterestClearsBothBeforeAnyPrincipal() {
        final List<LoanRepaymentScheduleInstallment> installments = twoOverdueInstallments();
        // penalties 20 + interest 10
        final Money payment = Money.of(CURRENCY, BigDecimal.valueOf(30));
        final LoanTransaction loanTransaction = LoanTransaction.repayment(office, payment, null, transactionDate, ExternalId.empty());

        final Money remaining = underTest.processTransaction(loanTransaction, CURRENCY, installments, new HashSet<>(), null);

        assertEquals(0, remaining.getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, loanTransaction.getPenaltyChargesPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(20)));
        assertEquals(0, loanTransaction.getInterestPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(10)));
        assertEquals(0, loanTransaction.getPrincipalPortion(CURRENCY).getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, installments.get(0).getPrincipalOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(100)));
        assertEquals(0, installments.get(1).getPrincipalOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(100)));
    }

    @Test
    public void paymentBeyondPenaltiesAndInterestAppliesRemainingToPrincipalOldestFirst() {
        final List<LoanRepaymentScheduleInstallment> installments = twoOverdueInstallments();
        // penalties 20 + interest 10 + principal 40 on installment 1
        final Money payment = Money.of(CURRENCY, BigDecimal.valueOf(70));
        final LoanTransaction loanTransaction = LoanTransaction.repayment(office, payment, null, transactionDate, ExternalId.empty());

        final Money remaining = underTest.processTransaction(loanTransaction, CURRENCY, installments, new HashSet<>(), null);

        assertEquals(0, remaining.getAmount().compareTo(BigDecimal.ZERO));
        assertEquals(0, loanTransaction.getPenaltyChargesPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(20)));
        assertEquals(0, loanTransaction.getInterestPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(10)));
        assertEquals(0, loanTransaction.getPrincipalPortion(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(40)));
        assertEquals(0, installments.get(0).getPrincipalOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(60)));
        assertEquals(0, installments.get(1).getPrincipalOutstanding(CURRENCY).getAmount().compareTo(BigDecimal.valueOf(100)));
    }

    private List<LoanRepaymentScheduleInstallment> twoOverdueInstallments() {
        final List<LoanRepaymentScheduleInstallment> installments = new ArrayList<>();
        // principal, interest, fee, penalty
        installments.add(new LoanRepaymentScheduleInstallment(loan, 1, LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 31),
                BigDecimal.valueOf(100), BigDecimal.valueOf(5), BigDecimal.ZERO, BigDecimal.valueOf(10), false, null, BigDecimal.ZERO));
        installments.add(new LoanRepaymentScheduleInstallment(loan, 2, LocalDate.of(2026, 1, 31), LocalDate.of(2026, 2, 5),
                BigDecimal.valueOf(100), BigDecimal.valueOf(5), BigDecimal.ZERO, BigDecimal.valueOf(10), false, null, BigDecimal.ZERO));
        return installments;
    }
}
