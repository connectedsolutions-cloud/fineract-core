/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.handler;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.commands.annotation.CommandType;
import org.apache.fineract.commands.handler.NewCommandSourceHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.portfolio.shareaccounts.service.ShareYieldService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@CommandType(entity = "SHAREACCOUNT", action = "SOURCEEXACTYIELDACCRUAL")
public class SourceExactShareYieldAccrualCommandHandler implements NewCommandSourceHandler {

    private final ShareYieldService shareYieldService;
    private final AccountingOperationalMigrationService operationalMigrationService;

    @Override
    @Transactional
    public CommandProcessingResult processCommand(JsonCommand command) {
        return operationalMigrationService.execute(() -> shareYieldService.importAccrual(command.entityId(), command));
    }
}
