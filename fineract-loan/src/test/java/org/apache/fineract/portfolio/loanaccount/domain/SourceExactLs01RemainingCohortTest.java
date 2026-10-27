/*
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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.SourceExactRepaymentAllocation;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

// First-due fixtures isolate principal/interest with zero fees; live writer checks retain full charge ownership validation.
class SourceExactLs01RemainingCohortTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private MockedStatic<MoneyHelper> moneyHelper;
    private CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor processor;
    private Loan loan;
    private LoanTransaction transaction;

    @BeforeEach
    void setUp() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), new PostDueAccruedInterestCalculator());
        loan = mock(Loan.class);
        var terms = mock(LoanProductRelatedDetail.class);
        when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
        when(terms.getAnnualNominalInterestRate()).thenReturn(BigDecimal.ZERO);
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
        moneyHelper.close();
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("earlyCases")
    void existingFixDefersInterestAndFinallyMapsBothFrozenComponents(String fixture) {
        var rows = prepare(fixture);
        var principal = transaction.getSourceExactPrincipalPortion(CURRENCY);
        var interest = transaction.getSourceExactInterestPortion(CURRENCY);
        assertMoney(principal.getAmount(), recalculate(List.of()));
        for (var row : rows) {
            assertMoney(BigDecimal.ZERO, row.getPrincipalCompleted(CURRENCY));
            assertMoney(BigDecimal.ZERO, row.getInterestPaid(CURRENCY));
        }
        var dates = rows.stream().map(LoanRepaymentScheduleInstallment::getDueDate).toList();
        assertMoney(BigDecimal.ZERO, processor.handleTransactionAndCharges(transaction, CURRENCY, rows, new HashSet<>(), null, false));
        assertMoney(principal.getAmount(), transaction.getPrincipalPortion(CURRENCY));
        assertMoney(interest.getAmount(), transaction.getInterestPortion(CURRENCY));
        assertMoney(principal.getAmount(),
                rows.stream().map(row -> row.getPrincipalCompleted(CURRENCY)).reduce(Money.zero(CURRENCY), Money::add));
        assertMoney(interest.getAmount(), rows.stream().map(row -> row.getInterestPaid(CURRENCY)).reduce(Money.zero(CURRENCY), Money::add));
        assertEquals(dates, rows.stream().map(LoanRepaymentScheduleInstallment::getDueDate).toList());
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("earlyCases")
    void missingContractualCoverageStillRejectsTheProvisionalPayment(String fixture) {
        prepare(fixture);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(List.of());
        assertThrows(GeneralPlatformDomainRuleException.class, () -> recalculate(List.of()));
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("earlyCases")
    void emptyFinalScheduleStillRejectsEvenWhenTheProvisionalPaymentWasAccepted(String fixture) {
        prepare(fixture);
        recalculate(List.of());
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> processor.handleTransactionAndCharges(transaction, CURRENCY, List.of(), new HashSet<>(), null, false));
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("firstDueCases")
    void nonemptyFirstDuePrefixRetainsTheOriginalPrincipalAndInterestRemainder(String fixture) {
        var rows = prepare(fixture);
        var values = fixture.split("\\|");
        var nativePrefix = new LoanRepaymentScheduleInstallment(loan, 1, LocalDate.parse(values[2]), rows.get(0).getDueDate(),
                new BigDecimal(values[10]), new BigDecimal(values[11]), BigDecimal.ZERO, BigDecimal.ZERO, false, null);
        var error = assertThrows(GeneralPlatformDomainRuleException.class, () -> recalculate(List.of(nativePrefix)));
        assertEquals(0, new BigDecimal(values[7]).compareTo((BigDecimal) error.getDefaultUserMessageArgs()[0]));
        assertEquals(0, new BigDecimal(values[8]).compareTo((BigDecimal) error.getDefaultUserMessageArgs()[1]));
        assertEquals("error.msg.loan.source.exact.allocation.not.representable", error.getGlobalisationMessageCode());
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("uncorrectedFirstDueCases")
    void frozenCalendarStillRejectsTheEightFirstDueInterestExcesses(String fixture) {
        var rows = prepare(fixture);
        var error = assertThrows(GeneralPlatformDomainRuleException.class, () -> recalculate(List.of(rows.get(0))));
        var values = fixture.split("\\|");
        assertEquals(0, new BigDecimal(values[8]).compareTo((BigDecimal) error.getDefaultUserMessageArgs()[1]));
    }

    @ParameterizedTest(name = "case {index}")
    @MethodSource("calendarCorrectionCases")
    void loan331FrozenCalendarCorrectsTheInitialZeroServicingInterestCapacity(String fixture) {
        // Frozen interest capacity is 32.55 versus native-prefix 27.12. This isolated
        // calendar comparison is not a claim of native replay success or LS-05 deferral.
        var rows = prepare(fixture);
        assertMoney(new BigDecimal("8.44"), recalculate(List.of(rows.get(0))));
        rows = prepare(fixture);
        assertMoney(BigDecimal.ZERO, processor.handleTransactionAndCharges(transaction, CURRENCY, rows, new HashSet<>(), null, false));
        assertMoney(new BigDecimal("47.12"), transaction.getPrincipalPortion(CURRENCY));
        assertMoney(new BigDecimal("32.55"), transaction.getInterestPortion(CURRENCY));
    }

    private Money recalculate(List<LoanRepaymentScheduleInstallment> rows) {
        return processor.handleRepaymentScheduleForInterestRecalculation(List.of(transaction), CURRENCY, rows, new HashSet<>());
    }

    private List<LoanRepaymentScheduleInstallment> prepare(String fixture) {
        var values = fixture.split("\\|");
        LocalDate disbursed = LocalDate.parse(values[2]), paid = LocalDate.parse(values[3]);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, paid)));
        when(loan.getDisbursementDate()).thenReturn(disbursed);
        var rows = new ArrayList<LoanRepaymentScheduleInstallment>();
        LocalDate from = disbursed;
        for (var encoded : values[9].split(";")) {
            var row = encoded.split(":");
            var due = LocalDate.parse(row[0]);
            rows.add(new LoanRepaymentScheduleInstallment(loan, rows.size() + 1, from, due, new BigDecimal(row[1]), new BigDecimal(row[2]),
                    BigDecimal.ZERO, BigDecimal.ZERO, false, null));
            from = due;
        }
        when(loan.getRepaymentScheduleInstallments()).thenReturn(rows);
        var principal = new BigDecimal(values[5]);
        var interest = new BigDecimal(values[6]);
        transaction = LoanTransaction.repayment(mock(Office.class), Money.of(CURRENCY, principal.add(interest)), null, paid,
                new ExternalId(values[4]));
        transaction.updateLoan(loan);
        transaction.markAsSourceExactAllocation(new SourceExactRepaymentAllocation(principal, interest, BigDecimal.ZERO, BigDecimal.ZERO));
        return rows;
    }

    static Stream<String> earlyCases() throws IOException {
        return fixtures().filter(line -> line.split("\\|")[1].equals("true"));
    }

    static Stream<String> firstDueCases() throws IOException {
        return fixtures().filter(line -> line.split("\\|")[1].equals("false"));
    }

    static Stream<String> uncorrectedFirstDueCases() throws IOException {
        return firstDueCases().filter(line -> !line.startsWith("loan:331|"));
    }

    static Stream<String> calendarCorrectionCases() throws IOException {
        return firstDueCases().filter(line -> line.startsWith("loan:331|"));
    }

    private static Stream<String> fixtures() throws IOException {
        try (var input = SourceExactLs01RemainingCohortTest.class.getResourceAsStream("/arissto/ls01-remaining-frozen-components.txt")) {
            return new String(input.readAllBytes(), StandardCharsets.UTF_8).lines()
                    .filter(line -> !line.startsWith("#") && !line.isBlank());
        }
    }

    private void assertMoney(BigDecimal expected, Money actual) {
        assertEquals(0, expected.compareTo(actual.getAmount()));
    }
}
