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
import java.lang.reflect.Type;
import java.time.LocalDate;
import java.util.LinkedHashMap;
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
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class LoanFreezeWritePlatformServiceImpl implements LoanFreezeWritePlatformService {

    private static final String EFFECTIVE_DATE = "effectiveDate";
    private static final String REASON = "reason";
    private static final Set<String> SUPPORTED_PARAMETERS = Set.of(EFFECTIVE_DATE, "dateFormat", "locale", REASON);
    private static final Type REQUEST_TYPE = new TypeToken<Map<String, Object>>() {}.getType();

    private final LoanRepositoryWrapper loanRepository;

    @Override
    @Transactional
    public CommandProcessingResult freeze(final Long loanId, final JsonCommand command) {
        command.checkForUnsupportedParameters(REQUEST_TYPE, command.parsedJson().toString(), SUPPORTED_PARAMETERS);

        final LocalDate effectiveDate = command.localDateValueOfParameterNamed(EFFECTIVE_DATE);
        final String reason = command.stringValueOfParameterNamedAllowingNull(REASON);
        final DataValidatorBuilder validator = new DataValidatorBuilder().resource("loan.freeze");
        validator.reset().parameter(EFFECTIVE_DATE).value(effectiveDate).notNull()
                .validateDateBeforeOrEqual(DateUtils.getBusinessLocalDate());
        validator.reset().parameter(REASON).value(reason).ignoreIfNull().notExceedingLengthOf(500);
        validator.throwValidationErrors();

        final Loan loan = loanRepository.findOneWithNotFoundDetection(loanId, true);
        if (!loan.getStatus().isActive()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.freeze.loan.is.not.active", "Only an active loan can be frozen.");
        }
        if (loan.isFrozen()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.freeze.loan.is.already.frozen", "The loan is already frozen.");
        }
        if (loan.getLastClosedBusinessDate() != null && !effectiveDate.isAfter(loan.getLastClosedBusinessDate())) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.freeze.effective.date.before.closed.boundary",
                    "The freeze effective date must be after the loan's last closed business date.");
        }

        loan.freeze(effectiveDate, reason, null);
        loanRepository.saveAndFlush(loan);

        final Map<String, Object> changes = new LinkedHashMap<>();
        changes.put("isFrozen", true);
        changes.put("frozenOn", effectiveDate);
        changes.put("freezeReason", reason);
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(loan.getId())
                .withEntityExternalId(loan.getExternalId()).withOfficeId(loan.getOfficeId()).withClientId(loan.getClientId())
                .withGroupId(loan.getGroupId()).withLoanId(loanId).with(changes).build();
    }
}
