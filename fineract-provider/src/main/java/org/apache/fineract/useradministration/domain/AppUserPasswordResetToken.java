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
package org.apache.fineract.useradministration.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_appuser_password_reset_token")
public class AppUserPasswordResetToken extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "appuser_id", nullable = false)
    private AppUser appUser;

    @Column(name = "token_hash", nullable = false, unique = true, length = 64)
    private String tokenHash;

    @Column(name = "expires_on_utc", nullable = false)
    private OffsetDateTime expiresOnUtc;

    @Column(name = "consumed_on_utc")
    private OffsetDateTime consumedOnUtc;

    @Column(name = "created_on_utc", nullable = false)
    private OffsetDateTime createdOnUtc;

    @Column(name = "last_requested_on_utc", nullable = false)
    private OffsetDateTime lastRequestedOnUtc;

    @Column(name = "request_count", nullable = false)
    private int requestCount;

    @Column(name = "failed_attempt_count", nullable = false)
    private int failedAttemptCount;

    @Column(name = "created_ip", length = 45)
    private String createdIp;

    protected AppUserPasswordResetToken() {}

    public static AppUserPasswordResetToken create(final AppUser appUser, final String tokenHash, final OffsetDateTime now,
            final OffsetDateTime expiresOnUtc, final String createdIp) {
        final AppUserPasswordResetToken token = new AppUserPasswordResetToken();
        token.appUser = appUser;
        token.tokenHash = tokenHash;
        token.createdOnUtc = now;
        token.lastRequestedOnUtc = now;
        token.expiresOnUtc = expiresOnUtc;
        token.requestCount = 1;
        token.failedAttemptCount = 0;
        token.createdIp = createdIp;
        return token;
    }

    public AppUser getAppUser() {
        return appUser;
    }

    public String getTokenHash() {
        return tokenHash;
    }

    public OffsetDateTime getExpiresOnUtc() {
        return expiresOnUtc;
    }

    public OffsetDateTime getConsumedOnUtc() {
        return consumedOnUtc;
    }

    public OffsetDateTime getCreatedOnUtc() {
        return createdOnUtc;
    }

    public int getFailedAttemptCount() {
        return failedAttemptCount;
    }

    public boolean isConsumed() {
        return consumedOnUtc != null;
    }

    public boolean isExpired(final OffsetDateTime now) {
        return expiresOnUtc != null && !expiresOnUtc.isAfter(now);
    }

    public boolean isUsable(final OffsetDateTime now) {
        return !isConsumed() && !isExpired(now);
    }

    public void consume(final OffsetDateTime now) {
        this.consumedOnUtc = now;
    }

    public int recordFailedAttempt(final OffsetDateTime now, final int maxFailedAttempts) {
        this.failedAttemptCount = this.failedAttemptCount + 1;
        if (this.failedAttemptCount >= maxFailedAttempts) {
            consume(now);
        }
        return this.failedAttemptCount;
    }
}
