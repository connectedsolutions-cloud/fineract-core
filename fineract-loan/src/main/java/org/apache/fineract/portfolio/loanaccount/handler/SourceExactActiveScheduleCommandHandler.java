/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 */
package org.apache.fineract.portfolio.loanaccount.handler;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.commands.annotation.CommandType;
import org.apache.fineract.commands.handler.NewCommandSourceHandler;
import org.apache.fineract.infrastructure.DataIntegrityErrorHandler;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.portfolio.loanaccount.service.LoanWritePlatformService;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.orm.jpa.JpaSystemException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@CommandType(entity = "LOAN", action = "SOURCEEXACTACTIVESCHEDULE")
public class SourceExactActiveScheduleCommandHandler implements NewCommandSourceHandler {

    private final LoanWritePlatformService writePlatformService;
    private final DataIntegrityErrorHandler dataIntegrityErrorHandler;

    @Transactional
    @Override
    public CommandProcessingResult processCommand(final JsonCommand command) {
        try {
            return writePlatformService.importSourceExactActiveSchedule(command.getLoanId(), command);
        } catch (final JpaSystemException | DataIntegrityViolationException exception) {
            dataIntegrityErrorHandler.handleDataIntegrityIssues(command, exception.getMostSpecificCause(), exception,
                    "loan.source.exact.active.schedule", "Source-exact active schedule");
            return CommandProcessingResult.empty();
        }
    }
}
