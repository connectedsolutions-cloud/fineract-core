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
package org.apache.fineract.portfolio.loanaccount.service;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.cutoff.AccountingCutoffMigrationValidationService;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeAction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Imports Arissto's dated whole-loan account restriction history without replaying financial transactions. */
@Service
@RequiredArgsConstructor
public class SourceExactFreezeHistoryService {

    private record SourceEvent(long sourceId, boolean blocked, LocalDate effectiveDate, String externalId) {
    }

    private final LoanRepositoryWrapper loanRepository;
    private final AccountingCutoffMigrationValidationService cutoffValidation;

    @Transactional
    public CommandProcessingResult importHistory(final Long loanId, final JsonCommand command) {
        final JsonObject payload = JsonParser.parseString(command.json()).getAsJsonObject();
        final String sourceSystem = text(payload, "sourceSystem");
        final String sourceLoanExternalId = text(payload, "sourceLoanExternalId");
        final LocalDate cutoffDate = isoDate(text(payload, "cutoffDate"));
        if (!"ARISSTO".equals(sourceSystem)) {
            throw invalid("source.system", "Historical freeze history requires the Arissto source system");
        }
        cutoffValidation.requireExactActiveCutoff(cutoffDate);

        final Loan loan = loanRepository.findOneWithNotFoundDetection(loanId, true);
        final boolean activeUnclosed = loan.getStatus().isActive() && loan.getLastClosedBusinessDate() == null;
        final boolean historicalRepaid = loan.getStatus().isClosedObligationsMet() && loan.getClosedOnDate() != null
                && loan.getClosedOnDate().isBefore(cutoffDate);
        // The domain freeze/unfreeze methods append restrictions and update their
        // flags only. They never reopen a repaid loan, reprocess cash or post GL.
        if ((!activeUnclosed && !historicalRepaid) || loan.getDisbursementDate() == null
                || loan.getExternalId().isEmpty() || !Objects.equals(loan.getExternalId().getValue(), sourceLoanExternalId)
                || !sourceLoanExternalId.matches("(PROOF:[a-z0-9][a-z0-9-]{0,23}:)?ARISSTO:CRD:[0-9]+")) {
            throw invalid("loan.state", "Historical freeze history requires an active unclosed or pre-cutoff repaid source-exact Arissto loan");
        }
        final String prefix = sourceLoanExternalId.substring(0, sourceLoanExternalId.indexOf("ARISSTO:CRD:"));
        final List<SourceEvent> events = parseEvents(payload, prefix, loan.getDisbursementDate(), cutoffDate);
        final List<LoanFreezeHistory> existing = loan.getFreezeHistory().stream()
                .filter(event -> event.getAction() == LoanFreezeAction.FREEZE || event.getAction() == LoanFreezeAction.UNFREEZE).toList();
        if (!existing.isEmpty()) {
            if (matches(existing, events)) {
                return result(loan, command, events.size(), true);
            }
            throw invalid("existing.history", "Historical freeze history conflicts with existing whole-loan events");
        }
        if (loan.isFrozen()) {
            throw invalid("existing.state", "Historical freeze history cannot replace an untracked frozen state");
        }
        for (final SourceEvent event : events) {
            if (event.blocked()) {
                loan.freeze(event.effectiveDate(), "Arissto loan account restriction", event.externalId());
            } else {
                loan.unfreeze(event.effectiveDate(), "Arissto loan account restriction", event.externalId());
            }
            // Same-day source transitions have an order even though their dates
            // tie. Assign each target ID before appending the next transition.
            loanRepository.saveAndFlush(loan);
        }
        return result(loan, command, events.size(), false);
    }

    private static List<SourceEvent> parseEvents(final JsonObject payload, final String prefix, final LocalDate disbursementDate,
            final LocalDate cutoffDate) {
        if (!payload.has("events") || !payload.get("events").isJsonArray()) {
            throw invalid("events", "Historical freeze history requires an ordered event array");
        }
        final JsonArray input = payload.getAsJsonArray("events");
        if (input.isEmpty()) {
            throw invalid("events.empty", "Historical freeze history cannot be empty");
        }
        final List<SourceEvent> result = new ArrayList<>();
        LocalDate previousDate = null;
        Long previousId = null;
        boolean previousBlocked = false;
        for (final JsonElement element : input) {
            if (!element.isJsonObject()) {
                throw invalid("event.invalid", "Historical freeze event must be an object");
            }
            final JsonObject row = element.getAsJsonObject();
            final long sourceId;
            final boolean blocked;
            try {
                sourceId = row.get("sourceEventId").getAsLong();
                blocked = row.get("blocked").getAsBoolean();
            } catch (final RuntimeException exception) {
                throw invalid("event.fields", "Historical freeze event requires a source ID and blocked state");
            }
            final LocalDate effectiveDate = isoDate(text(row, "effectiveDate"));
            if (sourceId <= 0 || effectiveDate.isBefore(disbursementDate) || !effectiveDate.isBefore(cutoffDate)
                    || previousDate != null && (effectiveDate.isBefore(previousDate)
                            || effectiveDate.equals(previousDate) && sourceId <= previousId)
                    || blocked == previousBlocked) {
                throw invalid("event.order", "Historical freeze events must alternate in dated source order before the cutoff");
            }
            final String externalId = prefix + "ARISSTO:AFI-BLOQUEO:" + sourceId;
            if (externalId.length() > 100) {
                throw invalid("event.identity", "Historical freeze source identity exceeds the target limit");
            }
            result.add(new SourceEvent(sourceId, blocked, effectiveDate, externalId));
            previousDate = effectiveDate;
            previousId = sourceId;
            previousBlocked = blocked;
        }
        return result;
    }

    private static boolean matches(final List<LoanFreezeHistory> existing, final List<SourceEvent> expected) {
        if (existing.size() != expected.size()) {
            return false;
        }
        for (int index = 0; index < existing.size(); index++) {
            final LoanFreezeHistory actual = existing.get(index);
            final SourceEvent source = expected.get(index);
            if (actual.getAction() != (source.blocked() ? LoanFreezeAction.FREEZE : LoanFreezeAction.UNFREEZE)
                    || !source.effectiveDate().equals(actual.getEffectiveDate())
                    || !source.externalId().equals(actual.getSourceEventExternalId())) {
                return false;
            }
        }
        return true;
    }

    private static String text(final JsonObject object, final String key) {
        if (!object.has(key) || object.get(key).isJsonNull()) {
            throw invalid("parameter.missing", "Missing historical freeze parameter: " + key);
        }
        return object.get(key).getAsString();
    }

    private static LocalDate isoDate(final String value) {
        try {
            return LocalDate.parse(value);
        } catch (final DateTimeParseException exception) {
            throw invalid("date.invalid", "Historical freeze dates must use yyyy-MM-dd");
        }
    }

    private static CommandProcessingResult result(final Loan loan, final JsonCommand command, final int count,
            final boolean alreadyImported) {
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(loan.getId()).withLoanId(loan.getId())
                .withEntityExternalId(loan.getExternalId()).withOfficeId(loan.getOfficeId()).withClientId(loan.getClientId())
                .withGroupId(loan.getGroupId()).with(Map.of("eventCount", count, "alreadyImported", alreadyImported)).build();
    }

    private static GeneralPlatformDomainRuleException invalid(final String suffix, final String message) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.freeze.history." + suffix, message);
    }
}
