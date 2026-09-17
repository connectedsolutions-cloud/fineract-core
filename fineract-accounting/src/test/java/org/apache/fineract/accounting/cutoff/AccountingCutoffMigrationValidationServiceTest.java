/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file distributed
 * with this work for additional information regarding copyright ownership. The ASF licenses this file to you under the Apache License,
 * Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions
 * and limitations under the License.
 */
package org.apache.fineract.accounting.cutoff;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.Optional;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.junit.jupiter.api.Test;

class AccountingCutoffMigrationValidationServiceTest {

    private static final LocalDate CUTOFF = LocalDate.of(2026, 9, 15);

    @Test
    void requiresTheExactActiveCutoff() {
        AccountingCutoffConfigurationRepository repository = mock(AccountingCutoffConfigurationRepository.class);
        AccountingCutoffConfiguration configuration = AccountingCutoffConfiguration.draft(CUTOFF, "America/El_Salvador", "hash");
        configuration.activate(1L, null, "active-hash");
        when(repository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID)).thenReturn(Optional.of(configuration));
        AccountingCutoffMigrationValidationService service = new AccountingCutoffMigrationValidationService(repository);

        assertThat(service.requireExactActiveCutoff(CUTOFF)).isEqualTo(CUTOFF);
        assertThatThrownBy(() -> service.requireExactActiveCutoff(CUTOFF.minusDays(1)))
                .isInstanceOf(GeneralPlatformDomainRuleException.class);
    }

    @Test
    void rejectsDraftConfiguration() {
        AccountingCutoffConfigurationRepository repository = mock(AccountingCutoffConfigurationRepository.class);
        when(repository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID))
                .thenReturn(Optional.of(AccountingCutoffConfiguration.draft(CUTOFF, "America/El_Salvador", "hash")));
        AccountingCutoffMigrationValidationService service = new AccountingCutoffMigrationValidationService(repository);

        assertThatThrownBy(() -> service.requireExactActiveCutoff(CUTOFF)).isInstanceOf(GeneralPlatformDomainRuleException.class);
    }
}
