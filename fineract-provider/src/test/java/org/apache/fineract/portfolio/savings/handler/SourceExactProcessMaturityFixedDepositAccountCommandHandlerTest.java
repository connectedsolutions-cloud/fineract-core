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
package org.apache.fineract.portfolio.savings.handler;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.function.Supplier;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.apache.fineract.portfolio.savings.service.DepositAccountWritePlatformService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class SourceExactProcessMaturityFixedDepositAccountCommandHandlerTest {

    @Mock
    private DepositAccountWritePlatformService writePlatformService;
    @Mock
    private AccountingOperationalMigrationService operationalMigrationService;
    @Mock
    private JsonCommand command;

    private SourceExactProcessMaturityFixedDepositAccountCommandHandler handler;

    @BeforeEach
    void setUp() {
        handler = new SourceExactProcessMaturityFixedDepositAccountCommandHandler(writePlatformService, operationalMigrationService);
        when(operationalMigrationService.execute(any())).thenAnswer(invocation -> {
            final Supplier<?> action = invocation.getArgument(0);
            return action.get();
        });
    }

    @Test
    void forwardsValidatedSourceAuthoritativeMaturity() {
        final LocalDate sourceMaturityDate = LocalDate.of(2026, 9, 5);
        final LocalDate sourceCutoffDate = LocalDate.of(2026, 9, 4);
        configureForcedMaturity(sourceMaturityDate, sourceCutoffDate, false);

        final CommandProcessingResult result = handler.processCommand(command);

        assertEquals(104L, result.getResourceId());
        verify(writePlatformService).updateMaturityDetails(104L, DepositAccountType.FIXED_DEPOSIT, false, false, null, true);
    }

    @Test
    void rejectsSideEffectsOnForcedSourceMaturity() {
        configureForcedMaturity(LocalDate.of(2026, 9, 5), LocalDate.of(2026, 9, 4), true);

        assertThrows(PlatformApiDataValidationException.class, () -> handler.processCommand(command));
        verifyNoInteractions(writePlatformService);
    }

    private void configureForcedMaturity(final LocalDate sourceMaturityDate, final LocalDate sourceCutoffDate,
            final boolean applyInstruction) {
        when(command.entityId()).thenReturn(104L);
        when(command.booleanPrimitiveValueOfParameterNamed("applyMaturityInstruction")).thenReturn(applyInstruction);
        when(command.hasParameter("postMaturityInterest")).thenReturn(true);
        when(command.booleanPrimitiveValueOfParameterNamed("postMaturityInterest")).thenReturn(false);
        when(command.hasParameter("forceSourceMaturity")).thenReturn(true);
        when(command.booleanPrimitiveValueOfParameterNamed("forceSourceMaturity")).thenReturn(true);
        when(command.hasParameter("sourceRolloverDate")).thenReturn(false);
        when(command.stringValueOfParameterNamed("sourceState")).thenReturn("MATURED");
        when(command.localDateValueOfParameterNamed("sourceMaturityDate")).thenReturn(sourceMaturityDate);
        when(command.localDateValueOfParameterNamed("sourceCutoffDate")).thenReturn(sourceCutoffDate);
    }
}
