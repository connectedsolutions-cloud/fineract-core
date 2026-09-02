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
package org.apache.fineract.portfolio.loanaccount.loanschedule.domain;

import static java.math.BigDecimal.ZERO;
import static org.apache.fineract.organisation.monetary.domain.MonetaryCurrency.fromApplicationCurrency;
import static org.apache.fineract.portfolio.common.domain.DayOfWeekType.INVALID;
import static org.apache.fineract.portfolio.common.domain.PeriodFrequencyType.MONTHS;
import static org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleType.CUMULATIVE;
import static org.apache.fineract.portfolio.loanproduct.domain.AmortizationMethod.EQUAL_PRINCIPAL;
import static org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod.DAILY;
import static org.apache.fineract.portfolio.loanproduct.domain.InterestMethod.DECLINING_BALANCE;
import static org.apache.fineract.portfolio.loanproduct.domain.LoanPreCloseInterestCalculationStrategy.NONE;
import static org.apache.fineract.portfolio.loanproduct.domain.RepaymentStartDateType.DISBURSEMENT_DATE;
import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.ApplicationCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.common.domain.DaysInMonthType;
import org.apache.fineract.portfolio.common.domain.DaysInYearType;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class LoanApplicationTermsTest {

    @BeforeEach
    void setUpTenantContext() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        MoneyHelper.initializeTenantRoundingMode("default", RoundingMode.HALF_EVEN.ordinal());
    }

    @AfterEach
    void resetTenantContext() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void shouldRoundCalculatedInstallmentUpToCurrencyPrecision() {
        BigDecimal result = LoanApplicationTerms.roundCalculatedInstallment(new BigDecimal("25.720001"), 2, true);

        assertEquals(new BigDecimal("25.73"), result);
    }

    @Test
    void shouldNotIncreaseAnExactCalculatedInstallment() {
        BigDecimal result = LoanApplicationTerms.roundCalculatedInstallment(new BigDecimal("25.720000"), 2, true);

        assertEquals(new BigDecimal("25.72"), result);
    }

    @Test
    void shouldPreserveNativeCalculationWhenRoundingIsDisabled() {
        BigDecimal installment = new BigDecimal("25.720001");

        assertEquals(installment, LoanApplicationTerms.roundCalculatedInstallment(installment, 2, false));
    }

    @Test
    void shouldUseTenantInterestRoundingForOrdinaryLoans() {
        BigDecimal result = LoanApplicationTerms.roundInterestForInstallment(new BigDecimal("3.935"), 2, RoundingMode.HALF_UP, false);

        assertEquals(new BigDecimal("3.94"), result);
    }

    @Test
    void shouldRoundHalfCentInterestDownForCredesalLoans() {
        BigDecimal result = LoanApplicationTerms.roundInterestForInstallment(new BigDecimal("3.935"), 2, RoundingMode.HALF_UP, true);

        assertEquals(new BigDecimal("3.93"), result);
    }

    @ParameterizedTest
    @MethodSource("dailyInterestDayCountCases")
    void shouldCalculateCumulativeDailyInterestUsingTheConfiguredDayCountConvention(final DaysInYearType daysInYearType,
            final LocalDate periodStartDate, final LocalDate periodEndDate, final String expectedInterest) {
        ApplicationCurrency applicationCurrency = new ApplicationCurrency("USD", "US Dollar", 2, 0, "currency.USD", "$");
        Money outstandingBalance = Money.of(fromApplicationCurrency(applicationCurrency), new BigDecimal("392.00"));
        LoanApplicationTerms terms = createDailyInterestTerms(applicationCurrency, outstandingBalance, daysInYearType, periodStartDate);

        PrincipalInterest result = terms.calculateTotalInterestForPeriod(new DefaultPaymentPeriodsInOneYearCalculator(), ZERO, 1,
                MathContext.DECIMAL64, outstandingBalance.zero(), outstandingBalance, periodStartDate, periodEndDate);

        assertEquals(new BigDecimal(expectedInterest), result.interest().getAmount());
    }

    private static Stream<Arguments> dailyInterestDayCountCases() {
        return Stream.of(Arguments.of(DaysInYearType.ACTUAL, LocalDate.of(2027, 6, 1), LocalDate.of(2027, 6, 16), "13.53"),
                Arguments.of(DaysInYearType.ACTUAL, LocalDate.of(2027, 12, 23), LocalDate.of(2028, 1, 7), "13.53"),
                Arguments.of(DaysInYearType.ACTUAL, LocalDate.of(2028, 1, 7), LocalDate.of(2028, 1, 22), "13.50"),
                Arguments.of(DaysInYearType.DAYS_365, LocalDate.of(2028, 1, 7), LocalDate.of(2028, 1, 22), "13.53"),
                Arguments.of(DaysInYearType.DAYS_360, LocalDate.of(2028, 1, 7), LocalDate.of(2028, 1, 22), "13.72"));
    }

    private LoanApplicationTerms createDailyInterestTerms(final ApplicationCurrency applicationCurrency, final Money principal,
            final DaysInYearType daysInYearType, final LocalDate expectedDisbursementDate) {
        return LoanApplicationTerms.assembleFrom(applicationCurrency.toData(), 3, MONTHS, 3, 1, MONTHS, null, INVALID, EQUAL_PRINCIPAL,
                DECLINING_BALANCE, new BigDecimal("7.00"), MONTHS, new BigDecimal("84.00"), DAILY, false, principal,
                expectedDisbursementDate, null, expectedDisbursementDate.plusMonths(1), null, null, null, null, null, principal.zero(),
                false, null, List.of(), principal.getAmount(), null, DaysInMonthType.ACTUAL, daysInYearType, false, null, null, null, null,
                null, ZERO, null, NONE, null, principal.getAmount(), new ArrayList<>(), false, 0, false, null, false, false, false, null,
                false, false, null, false, DISBURSEMENT_DATE, expectedDisbursementDate, CUMULATIVE, LoanScheduleProcessingType.HORIZONTAL,
                null, false, null, null, false, null, false, null, null, null, false, null, null, null, false);
    }
}
