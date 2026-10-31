/**
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;

import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeAction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistoryRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class LoanMoraFreezeWritePlatformServiceImplTest {
    @Mock private EntityManager entityManager;
    @Mock private LoanRepositoryWrapper loanRepository;
    @Mock private LoanFreezeHistoryRepository historyRepository;
    @Mock private Loan loan;
    @InjectMocks private LoanMoraFreezeWritePlatformServiceImpl service;
    private final List<LoanFreezeHistory> history = new ArrayList<>();

    @BeforeEach void setUp() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "UTC", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.parse("2026-10-24"))));
    }
    @AfterEach void tearDown() { ThreadLocalContextUtil.reset(); }
    private void activeLoan() {
        given(loanRepository.findOneWithNotFoundDetection(7L)).willReturn(loan);
        given(loan.getStatus()).willReturn(LoanStatus.ACTIVE);
        given(loan.getDisbursementDate()).willReturn(LocalDate.parse("2026-01-01"));
    }
    private JsonCommand command(String date) {
        var helper = new FromJsonHelper();
        return new JsonCommand(7L, helper.parse("{\"effectiveDate\":\"" + date + "\",\"dateFormat\":\"yyyy-MM-dd\",\"locale\":\"en\"}"), helper);
    }
    @Test void backdatedFreezeAndUnfreezeAreAcceptedWithoutWholeLoanMutation() {
        activeLoan();
        given(loan.getFreezeHistory()).willReturn(history);
        service.freeze(7L, command("2026-09-01"));
        verify(entityManager).lock(loan, LockModeType.PESSIMISTIC_WRITE);
        service.unfreeze(7L, command("2026-09-15"));
        assertThat(history).extracting(LoanFreezeHistory::getAction).containsExactly(LoanFreezeAction.MORA_FREEZE, LoanFreezeAction.MORA_UNFREEZE);
        verify(loan, never()).freeze(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        verify(loan, never()).getLastClosedBusinessDate();
    }
    @Test void futureDatesAreRejected() {
        assertThatThrownBy(() -> service.freeze(7L, command("2026-10-25"))).isInstanceOf(PlatformApiDataValidationException.class);
        assertThatThrownBy(() -> service.unfreeze(7L, command("2026-10-25"))).isInstanceOf(PlatformApiDataValidationException.class);
    }
    @Test void datesBeforeDisbursementAreRejected() {
        activeLoan();
        assertThatThrownBy(() -> service.freeze(7L, command("2025-12-31"))).isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("before disbursement");
    }
    @Test void invalidStateAndReverseChronologyAreRejected() {
        activeLoan();
        given(loan.getFreezeHistory()).willReturn(history);
        assertThatThrownBy(() -> service.unfreeze(7L, command("2026-09-01"))).hasMessageContaining("not frozen");
        service.freeze(7L, command("2026-09-01"));
        assertThatThrownBy(() -> service.freeze(7L, command("2026-09-02"))).hasMessageContaining("already frozen");
        assertThatThrownBy(() -> service.unfreeze(7L, command("2026-08-31"))).hasMessageContaining("before the last");
        service.unfreeze(7L, command("2026-09-15"));
        assertThatThrownBy(() -> service.freeze(7L, command("2026-09-14"))).hasMessageContaining("before the last");
        assertThat(history).hasSize(2);
    }
    @Test void inactiveLoanIsRejected() {
        given(loanRepository.findOneWithNotFoundDetection(7L)).willReturn(loan);
        given(loan.getStatus()).willReturn(LoanStatus.CLOSED_OBLIGATIONS_MET);
        assertThatThrownBy(() -> service.freeze(7L, command("2026-09-01"))).hasMessageContaining("active loan");
        verify(loanRepository, never()).saveAndFlush(loan);
    }
}
