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

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verify;

import java.time.LocalDate;
import java.util.HashMap;
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
class LoanFreezeWritePlatformServiceImplTest {

    private static final LocalDate BUSINESS_DATE = LocalDate.of(2026, 3, 20);

    @Mock
    private LoanRepositoryWrapper loanRepository;

    @Mock
    private Loan loan;

    @InjectMocks
    private LoanFreezeWritePlatformServiceImpl service;

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "UTC", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, BUSINESS_DATE)));
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void freezesAnActiveLoan() {
        given(loanRepository.findOneWithNotFoundDetection(7L, true)).willReturn(loan);
        given(loan.getStatus()).willReturn(LoanStatus.ACTIVE);

        service.freeze(7L, command("20 March 2026", "Court order"));

        verify(loan).freeze(BUSINESS_DATE, "Court order", null);
        verify(loanRepository).saveAndFlush(loan);
    }

    @Test
    void rejectsAnAlreadyFrozenLoan() {
        given(loanRepository.findOneWithNotFoundDetection(7L, true)).willReturn(loan);
        given(loan.getStatus()).willReturn(LoanStatus.ACTIVE);
        given(loan.isFrozen()).willReturn(true);

        assertThatThrownBy(() -> service.freeze(7L, command("20 March 2026", null))).isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("already frozen");
    }

    @Test
    void rejectsAFutureEffectiveDate() {
        assertThatThrownBy(() -> service.freeze(7L, command("21 March 2026", null))).isInstanceOf(PlatformApiDataValidationException.class);
    }

    private JsonCommand command(final String effectiveDate, final String reason) {
        final String reasonJson = reason == null ? "" : ", \"reason\": \"" + reason + "\"";
        final String json = "{\"effectiveDate\": \"" + effectiveDate + "\", \"dateFormat\": \"dd MMMM yyyy\", \"locale\": \"en\""
                + reasonJson + "}";
        final FromJsonHelper helper = new FromJsonHelper();
        return new JsonCommand(7L, helper.parse(json), helper);
    }
}
