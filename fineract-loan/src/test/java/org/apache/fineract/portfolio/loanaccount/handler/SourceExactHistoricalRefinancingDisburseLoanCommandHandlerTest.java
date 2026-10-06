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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.handler;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.cutoff.AccountingPostingOrigin;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanaccount.service.LoanWritePlatformService;
import org.apache.fineract.portfolio.loanaccount.service.SourceExactRefinancingRepairContext;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;

class SourceExactHistoricalRefinancingDisburseLoanCommandHandlerTest {

    @Test
    void scopesHistoricalRepairToAuthorizedMigrationCommand() {
        LoanWritePlatformService write = mock(LoanWritePlatformService.class);
        PlatformSecurityContext security = mock(PlatformSecurityContext.class);
        AppUser user = mock(AppUser.class);
        JsonCommand command = mock(JsonCommand.class);
        AccountingPostingContext posting = new AccountingPostingContext();
        SourceExactHistoricalRefinancingDisburseLoanCommandHandler handler = new SourceExactHistoricalRefinancingDisburseLoanCommandHandler(
                write, new AccountingOperationalMigrationService(security, posting));
        CommandProcessingResult result = CommandProcessingResult.empty();
        when(security.authenticatedUser()).thenReturn(user);
        when(command.entityId()).thenReturn(42L);
        when(write.disburseSourceExactTopupLoan(42L, command)).thenAnswer(invocation -> {
            assertThat(SourceExactRefinancingRepairContext.isActive()).isTrue();
            assertThat(posting.getOrigin()).isEqualTo(AccountingPostingOrigin.ARISSTO_OPERATIONAL_MIGRATION);
            return result;
        });

        assertThat(handler.processCommand(command)).isSameAs(result);
        assertThat(SourceExactRefinancingRepairContext.isActive()).isFalse();
        assertThat(posting.getOrigin()).isEqualTo(AccountingPostingOrigin.NATIVE_OPERATION);
        verify(user).validateHasPermissionTo(AccountingOperationalMigrationService.PERMISSION);
    }

    @Test
    void clearsRepairContextAfterFailure() {
        LoanWritePlatformService write = mock(LoanWritePlatformService.class);
        PlatformSecurityContext security = mock(PlatformSecurityContext.class);
        JsonCommand command = mock(JsonCommand.class);
        AccountingPostingContext posting = new AccountingPostingContext();
        when(security.authenticatedUser()).thenReturn(mock(AppUser.class));
        when(command.entityId()).thenReturn(42L);
        when(write.disburseSourceExactTopupLoan(42L, command)).thenThrow(new IllegalStateException("failure"));
        SourceExactHistoricalRefinancingDisburseLoanCommandHandler handler = new SourceExactHistoricalRefinancingDisburseLoanCommandHandler(
                write, new AccountingOperationalMigrationService(security, posting));

        assertThatThrownBy(() -> handler.processCommand(command)).isInstanceOf(IllegalStateException.class);
        assertThat(SourceExactRefinancingRepairContext.isActive()).isFalse();
        assertThat(posting.getOrigin()).isEqualTo(AccountingPostingOrigin.NATIVE_OPERATION);
    }
}
