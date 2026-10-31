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
package org.apache.fineract.portfolio.interestpauses.service;

import static org.apache.fineract.portfolio.loanaccount.domain.LoanStatus.ACTIVE;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTermVariations;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleType;
import org.apache.fineract.portfolio.loanaccount.rescheduleloan.domain.LoanTermVariationsRepository;
import org.apache.fineract.portfolio.loanaccount.service.LoanAssembler;
import org.apache.fineract.portfolio.loanaccount.service.LoanScheduleService;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.apache.fineract.portfolio.loanproduct.domain.InterestMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import java.math.BigDecimal;

class CredesalInterestPauseWritePlatformServiceTest {

    @AfterEach
    void resetContext() {
        ThreadLocalContextUtil.reset();
    }

    @ParameterizedTest
    @ValueSource(booleans = { false, true })
    void pauseKeepsPostMaturityOrMigratedActualInterestScheduleUntouched(final boolean migrated) {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 10, 20))));

        final Loan loan = mock(Loan.class);
        final LoanProductRelatedDetail detail = mock(LoanProductRelatedDetail.class);
        final LoanRepaymentScheduleInstallment installment = mock(LoanRepaymentScheduleInstallment.class);
        final LoanTermVariations savedVariation = mock(LoanTermVariations.class);
        final LoanTermVariationsRepository variationsRepository = mock(LoanTermVariationsRepository.class);
        final LoanAssembler loanAssembler = mock(LoanAssembler.class);
        final LoanScheduleService scheduleService = mock(LoanScheduleService.class);
        final var service = new InterestPauseWritePlatformServiceImpl(variationsRepository, mock(LoanRepositoryWrapper.class),
                loanAssembler, mock(BusinessEventNotifierService.class), scheduleService);
        when(loanAssembler.assembleFrom(42L, false)).thenReturn(loan);
        when(loan.getLoanStatus()).thenReturn(ACTIVE);
        when(loan.getStatus()).thenReturn(ACTIVE);
        when(loan.getSubmittedOnDate()).thenReturn(LocalDate.of(2025, 1, 1));
        when(loan.getMaturityDate()).thenReturn(LocalDate.of(2026, 9, 30));
        when(loan.getLoanRepaymentScheduleDetail()).thenReturn(detail);
        when(detail.getLoanScheduleType()).thenReturn(LoanScheduleType.CUMULATIVE);
        when(detail.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        when(detail.getInterestCalculationPeriodMethod()).thenReturn(InterestCalculationPeriodMethod.DAILY);
        when(loan.transactionProcessingStrategy()).thenReturn("credesal-accrued-interest-first-strategy");
        when(loan.isInterestBearing()).thenReturn(true);
        when(loan.getLoanTermVariations()).thenReturn(new ArrayList<>());
        final LoanRepaymentScheduleInstallment baseline = mock(LoanRepaymentScheduleInstallment.class);
        when(baseline.getDueDate()).thenReturn(LocalDate.of(2026, 10, 19));
        when(baseline.isMigrationMetricBaseline()).thenReturn(true);
        when(baseline.getMigrationInterestForecast()).thenReturn(BigDecimal.ZERO);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(migrated ? List.of(baseline, installment) : List.of(installment));
        when(installment.getDueDate()).thenReturn(migrated ? LocalDate.of(2026, 10, 30) : LocalDate.of(2026, 9, 30));
        when(variationsRepository.saveAndFlush(any())).thenReturn(savedVariation);
        when(savedVariation.getId()).thenReturn(1L);

        service.createInterestPause(42L, "2026-10-21", "2027-01-21", "yyyy-MM-dd", "en");

        verify(scheduleService, never()).regenerateScheduleWithReprocessingTransactions(loan);
    }
}
