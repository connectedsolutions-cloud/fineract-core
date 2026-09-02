/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.portfolio.savings.handler;

import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.portfolio.savings.service.DepositAccountWritePlatformService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UndoTransactionFixedDepositAccountCommandHandlerTest {

    @Mock
    private DepositAccountWritePlatformService writePlatformService;

    @Mock
    private JsonCommand command;

    @Mock
    private CommandProcessingResult result;

    @Test
    void forwardsSourceAuthoritativeCleanupFlag() {
        when(command.getTransactionId()).thenReturn("19626");
        when(command.entityId()).thenReturn(83L);
        when(command.booleanPrimitiveValueOfParameterNamed("sourceAuthoritativeCleanup")).thenReturn(true);
        when(writePlatformService.undoFDTransaction(83L, 19626L, false, true)).thenReturn(result);

        UndoTransactionFixedDepositAccountCommandHandler handler = new UndoTransactionFixedDepositAccountCommandHandler(
                writePlatformService);

        assertSame(result, handler.processCommand(command));
        verify(writePlatformService).undoFDTransaction(83L, 19626L, false, true);
    }
}
