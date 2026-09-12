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

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.HexFormat;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class AccountingCutoffConfigurationServiceImpl implements AccountingCutoffConfigurationService {

    public static final String TIMEZONE = "America/El_Salvador";
    private final AccountingCutoffConfigurationRepository repository;
    private final PlatformSecurityContext securityContext;

    @Override
    @Transactional(readOnly = true)
    public AccountingCutoffConfigurationData retrieve() {
        securityContext.authenticatedUser().validateHasPermissionTo("READ_ACCOUNTINGCUTOFF");
        return AccountingCutoffConfigurationData.from(requireConfiguration());
    }

    @Override
    @Transactional
    public AccountingCutoffConfigurationData configureDraft(AccountingCutoffConfigurationRequest request) {
        AppUser user = securityContext.authenticatedUser();
        user.validateHasPermissionTo("CONFIGURE_ACCOUNTINGCUTOFF");
        validateRequest(request);

        AccountingCutoffConfiguration configuration = repository.findById(AccountingCutoffConfiguration.SINGLETON_ID).orElse(null);
        if (configuration == null) {
            configuration = AccountingCutoffConfiguration.draft(request.cutoffDate(), TIMEZONE,
                    hash(request.cutoffDate(), TIMEZONE, AccountingCutoffLifecycleState.DRAFT, 1));
        } else {
            long nextRevision = configuration.getConfigurationRevision() + 1;
            configuration.updateDraft(request.cutoffDate(), TIMEZONE,
                    hash(request.cutoffDate(), TIMEZONE, AccountingCutoffLifecycleState.DRAFT, nextRevision));
        }
        return AccountingCutoffConfigurationData.from(repository.saveAndFlush(configuration));
    }

    @Override
    @Transactional
    public AccountingCutoffConfigurationData activate() {
        AppUser user = securityContext.authenticatedUser();
        user.validateHasPermissionTo("ACTIVATE_ACCOUNTINGCUTOFF");
        AccountingCutoffConfiguration configuration = requireConfiguration();
        long nextRevision = configuration.getConfigurationRevision() + 1;
        configuration.activate(user.getId(), DateUtils.getAuditOffsetDateTime(),
                hash(configuration.getCutoffDate(), configuration.getTimezoneId(), AccountingCutoffLifecycleState.ACTIVE, nextRevision));
        return AccountingCutoffConfigurationData.from(repository.saveAndFlush(configuration));
    }

    @Override
    @Transactional
    public AccountingCutoffConfigurationData seal() {
        AppUser user = securityContext.authenticatedUser();
        user.validateHasPermissionTo("SEAL_ACCOUNTINGCUTOFF");
        AccountingCutoffConfiguration configuration = requireConfiguration();
        long nextRevision = configuration.getConfigurationRevision() + 1;
        configuration.seal(user.getId(), DateUtils.getAuditOffsetDateTime(),
                hash(configuration.getCutoffDate(), configuration.getTimezoneId(), AccountingCutoffLifecycleState.SEALED, nextRevision));
        return AccountingCutoffConfigurationData.from(repository.saveAndFlush(configuration));
    }

    private AccountingCutoffConfiguration requireConfiguration() {
        return repository.findById(AccountingCutoffConfiguration.SINGLETON_ID)
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.accounting.cutoff.not.configured",
                        "The tenant accounting cutoff has not been configured"));
    }

    private void validateRequest(AccountingCutoffConfigurationRequest request) {
        if (request == null || request.cutoffDate() == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.accounting.cutoff.date.required",
                    "The accounting cutoff date is required");
        }
        if (request.timezoneId() != null && !TIMEZONE.equals(request.timezoneId())) {
            throw new GeneralPlatformDomainRuleException("error.msg.accounting.cutoff.timezone.invalid",
                    "The accounting cutoff timezone must be " + TIMEZONE);
        }
        ZoneId.of(TIMEZONE);
    }

    static String hash(LocalDate cutoffDate, String timezoneId, AccountingCutoffLifecycleState state, long revision) {
        String canonical = cutoffDate + "|" + timezoneId + "|" + state + "|" + revision;
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required for accounting cutoff configuration", exception);
        }
    }
}
