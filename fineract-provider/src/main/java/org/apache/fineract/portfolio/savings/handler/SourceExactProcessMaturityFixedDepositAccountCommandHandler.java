/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.portfolio.savings.handler;

import static org.apache.fineract.portfolio.savings.DepositsApiConstants.sourceRolloverDateParamName;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingOperationalMigrationService;
import org.apache.fineract.commands.annotation.CommandType;
import org.apache.fineract.commands.handler.NewCommandSourceHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.data.DataValidatorBuilder;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.apache.fineract.portfolio.savings.service.DepositAccountWritePlatformService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@CommandType(entity = "FIXEDDEPOSITACCOUNT", action = "SOURCEEXACTPROCESSMATURITY")
public class SourceExactProcessMaturityFixedDepositAccountCommandHandler implements NewCommandSourceHandler {

    private final DepositAccountWritePlatformService writePlatformService;
    private final AccountingOperationalMigrationService operationalMigrationService;

    @Transactional
    @Override
    public CommandProcessingResult processCommand(final JsonCommand command) {
        return this.operationalMigrationService.execute(() -> {
            final Long accountId = command.entityId();
            final boolean applyInstruction = command.booleanPrimitiveValueOfParameterNamed("applyMaturityInstruction");
            final boolean postInterest = !command.hasParameter("postMaturityInterest")
                    || command.booleanPrimitiveValueOfParameterNamed("postMaturityInterest");
            final boolean forceSourceMaturity = command.hasParameter("forceSourceMaturity")
                    && command.booleanPrimitiveValueOfParameterNamed("forceSourceMaturity");
            final LocalDate rolloverDate = command.hasParameter(sourceRolloverDateParamName)
                    ? command.localDateValueOfParameterNamed(sourceRolloverDateParamName)
                    : null;
            if (forceSourceMaturity) {
                validateSourceMaturityEvidence(command, applyInstruction, postInterest);
            }
            final Long reinvestedId = this.writePlatformService.updateMaturityDetails(accountId,
                    DepositAccountType.FIXED_DEPOSIT, applyInstruction, postInterest, rolloverDate, forceSourceMaturity);
            final CommandProcessingResultBuilder result = new CommandProcessingResultBuilder().withEntityId(accountId)
                    .withSavingsId(accountId);
            if (reinvestedId != null) {
                result.withSubEntityId(reinvestedId).with(Map.of("reinvestedDepositId", reinvestedId));
            }
            return result.build();
        });
    }

    private static void validateSourceMaturityEvidence(final JsonCommand command, final boolean applyInstruction,
            final boolean postInterest) {
        final List<ApiParameterError> errors = new ArrayList<>();
        final DataValidatorBuilder validator = new DataValidatorBuilder(errors).resource("fixeddepositaccount.source.maturity");
        final String sourceState = command.stringValueOfParameterNamed("sourceState");
        final LocalDate sourceMaturityDate = command.localDateValueOfParameterNamed("sourceMaturityDate");
        final LocalDate sourceCutoffDate = command.localDateValueOfParameterNamed("sourceCutoffDate");
        validator.reset().parameter("sourceState").value(sourceState).notNull().isOneOfTheseStringValues("matured");
        validator.reset().parameter("sourceMaturityDate").value(sourceMaturityDate).notNull();
        validator.reset().parameter("sourceCutoffDate").value(sourceCutoffDate).notNull();
        validator.reset().parameter("applyMaturityInstruction").value(applyInstruction).isOneOfTheseValues(false);
        validator.reset().parameter("postMaturityInterest").value(postInterest).isOneOfTheseValues(false);
        if (!errors.isEmpty()) {
            throw new PlatformApiDataValidationException(errors);
        }
    }
}
