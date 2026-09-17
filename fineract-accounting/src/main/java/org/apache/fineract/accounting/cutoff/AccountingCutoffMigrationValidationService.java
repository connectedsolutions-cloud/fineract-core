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
package org.apache.fineract.accounting.cutoff;

import java.time.LocalDate;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class AccountingCutoffMigrationValidationService {

    private final AccountingCutoffConfigurationRepository repository;

    public LocalDate requireExactActiveCutoff(final LocalDate requestedCutoffDate) {
        final AccountingCutoffConfiguration cutoff = repository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID)
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.accounting.cutoff.not.configured",
                        "The tenant accounting cutoff has not been configured"));
        if (requestedCutoffDate == null || cutoff.getLifecycleState() != AccountingCutoffLifecycleState.ACTIVE
                || !requestedCutoffDate.equals(cutoff.getCutoffDate())) {
            throw new GeneralPlatformDomainRuleException("error.msg.accounting.cutoff.migration.date.invalid",
                    "The migration request requires the exact active accounting cutoff date");
        }
        return cutoff.getCutoffDate();
    }
}
