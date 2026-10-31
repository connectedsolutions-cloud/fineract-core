/**
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import com.google.gson.reflect.TypeToken;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import java.lang.reflect.Type;
import java.time.LocalDate;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.data.DataValidatorBuilder;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeAction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanFreezeHistoryRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanMoraFreezePeriods;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class LoanMoraFreezeWritePlatformServiceImpl implements LoanMoraFreezeWritePlatformService {
    private static final Set<String> SUPPORTED_PARAMETERS = Set.of("effectiveDate", "reason", "dateFormat", "locale");
    private static final Type REQUEST_TYPE = new TypeToken<Map<String, Object>>() {}.getType();
    private final EntityManager entityManager;
    private final LoanRepositoryWrapper loanRepository;
    private final LoanFreezeHistoryRepository historyRepository;

    @Override
    @Transactional
    public CommandProcessingResult freeze(final Long loanId, final JsonCommand command) {
        return change(loanId, command, true);
    }

    @Override
    @Transactional
    public CommandProcessingResult unfreeze(final Long loanId, final JsonCommand command) {
        return change(loanId, command, false);
    }

    private CommandProcessingResult change(final Long loanId, final JsonCommand command, final boolean freeze) {
        command.checkForUnsupportedParameters(REQUEST_TYPE, command.parsedJson().toString(), SUPPORTED_PARAMETERS);
        final LocalDate date = command.localDateValueOfParameterNamed("effectiveDate");
        final String reason = command.stringValueOfParameterNamedAllowingNull("reason");
        final DataValidatorBuilder validator = new DataValidatorBuilder().resource("loan.mora.freeze");
        validator.reset().parameter("effectiveDate").value(date).notNull().validateDateBeforeOrEqual(DateUtils.getBusinessLocalDate());
        validator.reset().parameter("reason").value(reason).ignoreIfNull().notExceedingLengthOf(500);
        validator.throwValidationErrors();
        final Loan loan = loanRepository.findOneWithNotFoundDetection(loanId);
        entityManager.lock(loan, LockModeType.PESSIMISTIC_WRITE);
        if (!loan.getStatus().isActive()) {
            throw invalid("loan.is.not.active", "Mora freeze controls require an active loan.");
        }
        if (loan.getDisbursementDate() == null || date.isBefore(loan.getDisbursementDate())) {
            throw invalid("before.disbursement", "The effective date cannot be before disbursement.");
        }
        final var history = loan.getFreezeHistory();
        final LocalDate lastDate = history.stream().filter(event -> isMoraAction(event.getAction()))
                .map(LoanFreezeHistory::getEffectiveDate).max(LocalDate::compareTo).orElse(null);
        if (lastDate != null && date.isBefore(lastDate)) {
            throw invalid("before.last.event", "The effective date cannot be before the last mora freeze or unfreeze event.");
        }
        if (LoanMoraFreezePeriods.isMoraFrozen(history, DateUtils.getBusinessLocalDate()) == freeze) {
            throw invalid("invalid.state", freeze ? "Mora is already frozen." : "Mora is not frozen by a mora-only control.");
        }
        // Backdating intentionally does not reverse charges, reprocess repayments or rewrite GL.
        history.add(new LoanFreezeHistory(loan, freeze ? LoanFreezeAction.MORA_FREEZE : LoanFreezeAction.MORA_UNFREEZE,
                date, reason, null));
        loanRepository.saveAndFlush(loan);
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(loanId).withLoanId(loanId)
                .withOfficeId(loan.getOfficeId()).withClientId(loan.getClientId()).withGroupId(loan.getGroupId())
                .with(Map.of("moraFrozen", freeze, "effectiveDate", date)).build();
    }

    @Override
    @Transactional(readOnly = true)
    public Map<String, Object> read(final Long loanId) {
        final Loan loan = loanRepository.findOneWithNotFoundDetection(loanId);
        final var history = historyRepository.findDataByLoanIdOrderByEffectiveDateAscIdAsc(loanId).stream()
                .filter(event -> isMoraAction(event.action())).toList();
        final boolean frozen = LoanMoraFreezePeriods.isMoraFrozen(loan.getFreezeHistory(), DateUtils.getBusinessLocalDate());
        return Map.of("moraFrozen", frozen, "wholeLoanFrozen", loan.isFrozenOn(DateUtils.getBusinessLocalDate()), "history", history);
    }

    private static boolean isMoraAction(final LoanFreezeAction action) {
        return action == LoanFreezeAction.MORA_FREEZE || action == LoanFreezeAction.MORA_UNFREEZE;
    }

    private static GeneralPlatformDomainRuleException invalid(final String code, final String message) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.mora.freeze." + code, message);
    }
}
