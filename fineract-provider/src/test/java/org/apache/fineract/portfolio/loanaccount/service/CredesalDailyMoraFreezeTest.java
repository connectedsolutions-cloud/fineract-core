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

import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeAction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class CredesalDailyMoraFreezeTest {
    private static final LocalDate BUSINESS_DATE = LocalDate.parse("2026-10-24");
    @Mock private LoanAssembler loanAssembler;
    @Mock private Loan loan;
    @Mock private LoanProduct product;
    @InjectMocks private LoanChargeWritePlatformServiceImpl service;

    @Test void dailyMoraSkipsAMoraOnlyFrozenLoanBeforeAnyChargeProcessing() {
        when(loanAssembler.assembleFrom(7L)).thenReturn(loan);
        when(loan.getFreezeHistory()).thenReturn(List.of(event(LoanFreezeAction.MORA_FREEZE, "2026-09-01")));
        try (var dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(BUSINESS_DATE);
            service.applyCredesalDailyMoraForLoan(7L);
        }
        verify(loan, never()).getLoanProduct();
    }

    @Test void unfreezeResumesDailyMoraProcessing() {
        when(loanAssembler.assembleFrom(7L)).thenReturn(loan);
        when(loan.getFreezeHistory()).thenReturn(List.of(event(LoanFreezeAction.MORA_FREEZE, "2026-09-01"),
                event(LoanFreezeAction.MORA_UNFREEZE, "2026-09-15")));
        when(loan.getStatus()).thenReturn(LoanStatus.ACTIVE);
        when(loan.getLoanProduct()).thenReturn(product);
        when(product.getCharges()).thenReturn(List.of());
        try (var dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(BUSINESS_DATE);
            service.applyCredesalDailyMoraForLoan(7L);
        }
        verify(loan).getLoanProduct();
    }

    @Test void separateWholeLoanFreezeStillStopsMora() {
        when(loanAssembler.assembleFrom(7L)).thenReturn(loan);
        when(loan.isFrozenOn(BUSINESS_DATE)).thenReturn(true);
        try (var dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(BUSINESS_DATE);
            service.applyCredesalDailyMoraForLoan(7L);
        }
        verify(loan, never()).getLoanProduct();
    }

    private LoanFreezeHistory event(LoanFreezeAction action, String date) {
        return new LoanFreezeHistory(loan, action, LocalDate.parse(date), null, null);
    }
}
