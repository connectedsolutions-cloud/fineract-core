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
package org.apache.fineract.accounting.cutoff;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class AccountingCutoffPolicyServiceImpl implements AccountingCutoffPolicyService {

    private final AccountingCutoffConfigurationRepository repository;
    private final AccountingPostingContext postingContext;

    @Override
    public AccountingCutoffDecision decide(AccountingPostingOrigin origin, LocalDate accountingDate) {
        if (accountingDate == null) {
            return AccountingCutoffDecision.REJECT;
        }
        AccountingCutoffConfiguration configuration = repository.findById(AccountingCutoffConfiguration.SINGLETON_ID).orElse(null);
        if (configuration == null || configuration.getLifecycleState() == AccountingCutoffLifecycleState.DRAFT) {
            return origin == AccountingPostingOrigin.NATIVE_OPERATION ? AccountingCutoffDecision.POST : AccountingCutoffDecision.REJECT;
        }

        boolean historical = accountingDate.isBefore(configuration.getCutoffDate());
        if (!historical) {
            return origin == AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT ? AccountingCutoffDecision.REJECT
                    : AccountingCutoffDecision.POST;
        }
        if (configuration.getLifecycleState() == AccountingCutoffLifecycleState.SEALED) {
            return AccountingCutoffDecision.REJECT;
        }
        return switch (origin) {
            case ARISSTO_OPERATIONAL_MIGRATION -> AccountingCutoffDecision.SUPPRESS_NATIVE_GL;
            case ARISSTO_HISTORICAL_GL_IMPORT -> AccountingCutoffDecision.POST;
            case NATIVE_OPERATION -> AccountingCutoffDecision.REJECT;
        };
    }

    @Override
    public boolean shouldGenerateAccounting(LocalDate accountingDate) {
        AccountingCutoffDecision decision = decide(postingContext.getOrigin(), accountingDate);
        if (decision == AccountingCutoffDecision.REJECT) {
            throw violation(accountingDate, "posting.rejected");
        }
        return decision == AccountingCutoffDecision.POST;
    }

    @Override
    public boolean shouldGenerateAccountingForBatch(Collection<LocalDate> accountingDates) {
        List<Boolean> decisions = accountingDates.stream().map(this::shouldGenerateAccounting).distinct().toList();
        if (decisions.size() > 1) {
            throw violation(null, "mixed.accounting.batch");
        }
        return decisions.isEmpty() || decisions.get(0);
    }

    @Override
    public void assertJournalPersistenceAllowed(LocalDate accountingDate) {
        AccountingCutoffDecision decision = decide(postingContext.getOrigin(), accountingDate);
        if (decision != AccountingCutoffDecision.POST) {
            String reason = decision == AccountingCutoffDecision.SUPPRESS_NATIVE_GL ? "suppressed.journal.reached.persistence"
                    : "journal.persistence.rejected";
            throw violation(accountingDate, reason);
        }
    }

    private AccountingCutoffViolationException violation(LocalDate accountingDate, String reason) {
        return new AccountingCutoffViolationException(reason, accountingDate, postingContext.getOrigin());
    }
}
