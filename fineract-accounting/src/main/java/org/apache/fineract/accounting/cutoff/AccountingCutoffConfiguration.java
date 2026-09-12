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

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "acc_accounting_cutoff_configuration")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AccountingCutoffConfiguration {

    public static final long SINGLETON_ID = 1L;

    @Id
    private Long id;

    @Column(name = "cutoff_date", nullable = false)
    private LocalDate cutoffDate;

    @Column(name = "timezone_id", nullable = false, length = 64)
    private String timezoneId;

    @Enumerated(EnumType.STRING)
    @Column(name = "lifecycle_state", nullable = false, length = 16)
    private AccountingCutoffLifecycleState lifecycleState;

    @Column(name = "configuration_revision", nullable = false)
    private long configurationRevision;

    @Column(name = "configuration_hash", nullable = false, length = 64)
    private String configurationHash;

    @Column(name = "activated_at")
    private OffsetDateTime activatedAt;

    @Column(name = "activated_by")
    private Long activatedBy;

    @Column(name = "sealed_at")
    private OffsetDateTime sealedAt;

    @Column(name = "sealed_by")
    private Long sealedBy;

    @Version
    private Long version;

    public static AccountingCutoffConfiguration draft(LocalDate cutoffDate, String timezoneId, String hash) {
        AccountingCutoffConfiguration configuration = new AccountingCutoffConfiguration();
        configuration.id = SINGLETON_ID;
        configuration.cutoffDate = cutoffDate;
        configuration.timezoneId = timezoneId;
        configuration.lifecycleState = AccountingCutoffLifecycleState.DRAFT;
        configuration.configurationRevision = 1;
        configuration.configurationHash = hash;
        return configuration;
    }

    public void updateDraft(LocalDate cutoffDate, String timezoneId, String hash) {
        requireState(AccountingCutoffLifecycleState.DRAFT);
        this.cutoffDate = cutoffDate;
        this.timezoneId = timezoneId;
        this.configurationRevision++;
        this.configurationHash = hash;
    }

    public void activate(Long userId, OffsetDateTime at, String hash) {
        requireState(AccountingCutoffLifecycleState.DRAFT);
        this.lifecycleState = AccountingCutoffLifecycleState.ACTIVE;
        this.activatedBy = userId;
        this.activatedAt = at;
        this.configurationRevision++;
        this.configurationHash = hash;
    }

    public void seal(Long userId, OffsetDateTime at, String hash) {
        requireState(AccountingCutoffLifecycleState.ACTIVE);
        this.lifecycleState = AccountingCutoffLifecycleState.SEALED;
        this.sealedBy = userId;
        this.sealedAt = at;
        this.configurationRevision++;
        this.configurationHash = hash;
    }

    private void requireState(AccountingCutoffLifecycleState expected) {
        if (lifecycleState != expected) {
            throw new AccountingCutoffViolationException("invalid.lifecycle.transition", null, lifecycleState, expected);
        }
    }
}
