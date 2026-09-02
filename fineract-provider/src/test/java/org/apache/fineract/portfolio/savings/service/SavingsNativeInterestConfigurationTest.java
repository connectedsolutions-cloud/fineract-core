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
package org.apache.fineract.portfolio.savings.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.Collection;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.portfolio.savings.SavingsCompoundingInterestPeriodType;
import org.apache.fineract.portfolio.savings.SavingsPostingInterestPeriodType;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.junit.jupiter.api.Test;

class SavingsNativeInterestConfigurationTest {

    @Test
    void shouldExposeActualInSavingsDayCountOptions() {
        final Collection<EnumOptionData> options = new SavingsDropdownReadPlatformServiceImpl()
                .retrieveInterestCalculationDaysInYearTypeOptions();

        assertEquals("savingsInterestCalculationDaysInYearType.actual",
                options.stream().filter(option -> option.getId() == 1L).findFirst().orElseThrow().getCode());
    }

    @Test
    void shouldExposeActivationAnchoredPostingAndCompoundingOptions() {
        final SavingsDropdownReadPlatformServiceImpl dropdowns = new SavingsDropdownReadPlatformServiceImpl();

        assertEquals("savings.interest.posting.period.savingsPostingInterestPeriodType.monthlyOnActivationDate",
                dropdowns.retrieveInterestPostingPeriodTypeOptions().stream().filter(option -> option.getId() == 9L).findFirst()
                        .orElseThrow().getCode());
        assertEquals("savings.interest.period.savingsCompoundingInterestPeriodType.monthlyOnActivationDate",
                dropdowns.retrieveCompoundingInterestPeriodTypeOptions().stream().filter(option -> option.getId() == 9L).findFirst()
                        .orElseThrow().getCode());
    }

    @Test
    void shouldResolveAccrualPeriodsFromTheirMatchingAccountFields() {
        final SavingsAccount account = mock(SavingsAccount.class);
        when(account.getInterestPostingPeriodType()).thenReturn(SavingsPostingInterestPeriodType.QUATERLY.getValue());
        when(account.getInterestCompoundingPeriodType()).thenReturn(SavingsCompoundingInterestPeriodType.MONTHLY.getValue());

        assertEquals(SavingsPostingInterestPeriodType.QUATERLY, SavingsAccrualWritePlatformServiceImpl.resolvePostingPeriodType(account));
        assertEquals(SavingsCompoundingInterestPeriodType.MONTHLY,
                SavingsAccrualWritePlatformServiceImpl.resolveCompoundingPeriodType(account));
    }
}
