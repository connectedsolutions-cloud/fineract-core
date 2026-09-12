/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.portfolio.savings.handler;

import java.util.Collection;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.commands.annotation.CommandType;
import org.apache.fineract.commands.handler.NewCommandSourceHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.portfolio.account.data.AccountTransferDTO;
import org.apache.fineract.portfolio.account.service.AccountTransfersWritePlatformService;
import org.apache.fineract.portfolio.savings.service.DepositAccountReadPlatformService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@CommandType(entity = "FIXEDDEPOSITACCOUNT", action = "SOURCEEXACTTRANSFERINTEREST")
public class SourceExactTransferInterestFixedDepositAccountCommandHandler implements NewCommandSourceHandler {

    private final DepositAccountReadPlatformService readPlatformService;
    private final AccountTransfersWritePlatformService accountTransfersWritePlatformService;
    private final AccountingOperationalMigrationService operationalMigrationService;

    @Transactional
    @Override
    public CommandProcessingResult processCommand(final JsonCommand command) {
        return this.operationalMigrationService.execute(() -> {
            final Long accountId = command.entityId();
            final Collection<AccountTransferDTO> transfers = this.readPlatformService.retrieveDataForInterestTransfer(accountId);
            for (final AccountTransferDTO transfer : transfers) {
                this.accountTransfersWritePlatformService.transferFunds(transfer);
            }
            return new CommandProcessingResultBuilder().withEntityId(accountId).withSavingsId(accountId)
                    .with(Map.of("transferredInterestCount", transfers.size())).build();
        });
    }
}
