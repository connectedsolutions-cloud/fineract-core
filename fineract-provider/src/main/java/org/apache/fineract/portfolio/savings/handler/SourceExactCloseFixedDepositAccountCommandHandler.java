/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.portfolio.savings.handler;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.commands.annotation.CommandType;
import org.apache.fineract.commands.handler.NewCommandSourceHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.portfolio.savings.service.DepositAccountWritePlatformService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@CommandType(entity = "FIXEDDEPOSITACCOUNT", action = "SOURCEEXACTCLOSE")
public class SourceExactCloseFixedDepositAccountCommandHandler implements NewCommandSourceHandler {

    private final DepositAccountWritePlatformService writePlatformService;
    private final AccountingOperationalMigrationService operationalMigrationService;

    @Transactional
    @Override
    public CommandProcessingResult processCommand(final JsonCommand command) {
        return this.operationalMigrationService.execute(() -> this.writePlatformService.closeFDAccount(command.entityId(), command));
    }
}
