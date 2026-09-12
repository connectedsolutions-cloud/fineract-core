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
package org.apache.fineract.portfolio.loanaccount.handler;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.cutoff.AccountingPostingOrigin;
import org.apache.fineract.infrastructure.DataIntegrityErrorHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanaccount.service.LoanWritePlatformService;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;

class SourceExactDisburseLoanCommandHandlerTest {

    @Test
    void authorizesAndScopesMigrationOriginAroundDisbursement() {
        LoanWritePlatformService writePlatformService = mock(LoanWritePlatformService.class);
        PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
        AppUser user = mock(AppUser.class);
        JsonCommand command = mock(JsonCommand.class);
        AccountingPostingContext postingContext = new AccountingPostingContext();
        AccountingOperationalMigrationService migrationService = new AccountingOperationalMigrationService(securityContext, postingContext);
        SourceExactDisburseLoanCommandHandler handler = new SourceExactDisburseLoanCommandHandler(writePlatformService,
                mock(DataIntegrityErrorHandler.class), migrationService);
        CommandProcessingResult expected = CommandProcessingResult.empty();
        when(securityContext.authenticatedUser()).thenReturn(user);
        when(command.entityId()).thenReturn(42L);
        when(writePlatformService.disburseLoan(42L, command, false)).thenAnswer(invocation -> {
            assertThat(postingContext.getOrigin()).isEqualTo(AccountingPostingOrigin.ARISSTO_OPERATIONAL_MIGRATION);
            return expected;
        });

        assertThat(handler.processCommand(command)).isSameAs(expected);
        assertThat(postingContext.getOrigin()).isEqualTo(AccountingPostingOrigin.NATIVE_OPERATION);
        verify(user).validateHasPermissionTo(AccountingOperationalMigrationService.PERMISSION);
    }
}
