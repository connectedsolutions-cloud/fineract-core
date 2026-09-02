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
package org.apache.fineract.useradministration.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.config.FineractProperties;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.EmailDetail;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.service.PlatformEmailSendException;
import org.apache.fineract.infrastructure.core.service.PlatformEmailService;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.service.PlatformPasswordEncoder;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserPasswordResetToken;
import org.apache.fineract.useradministration.domain.AppUserPasswordResetTokenRepository;
import org.apache.fineract.useradministration.domain.AppUserPreviousPassword;
import org.apache.fineract.useradministration.domain.AppUserPreviousPasswordRepository;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.apache.fineract.useradministration.domain.PasswordValidationPolicy;
import org.apache.fineract.useradministration.domain.PasswordValidationPolicyRepository;
import org.apache.fineract.useradministration.exception.PasswordResetTokenInvalidException;
import org.apache.fineract.useradministration.exception.PasswordSameAsCurrentException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;

@ExtendWith(MockitoExtension.class)
class PasswordResetWritePlatformServiceImplTest {

    @Mock
    private AppUserRepository appUserRepository;
    @Mock
    private AppUserPasswordResetTokenRepository passwordResetTokenRepository;
    @Mock
    private PasswordValidationPolicyRepository passwordValidationPolicyRepository;
    @Mock
    private AppUserPreviousPasswordRepository appUserPreviousPasswordRepository;
    @Mock
    private PlatformPasswordEncoder platformPasswordEncoder;
    @Mock
    private PlatformEmailService emailService;
    @Mock
    private FineractProperties fineractProperties;
    @Mock
    private AppUser user;
    @Mock
    private PasswordValidationPolicy passwordPolicy;

    private PasswordResetWritePlatformServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new PasswordResetWritePlatformServiceImpl(new FromJsonHelper(), appUserRepository, passwordResetTokenRepository,
                passwordValidationPolicyRepository, appUserPreviousPasswordRepository, platformPasswordEncoder, emailService,
                fineractProperties);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "Asia/Kolkata", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil
                .setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.now(ZoneId.systemDefault()))));
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void requestUnknownUsernameReturnsGenericSuccessAndSendsNoEmail() {
        when(appUserRepository.findAppUserByName("nobody")).thenReturn(null);

        final Map<String, String> result = service.requestPasswordReset("{\"username\":\"nobody\"}", "127.0.0.1");

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_REQUEST_MESSAGE, result.get("message"));
        verify(emailService, never()).sendDefinedEmail(any());
        verify(passwordResetTokenRepository, never()).saveAndFlush(any());
    }

    @Test
    void requestDisabledUserReturnsGenericSuccessAndSendsNoEmail() {
        when(user.isDeleted()).thenReturn(false);
        when(user.isEnabled()).thenReturn(false);
        when(appUserRepository.findAppUserByName("ada")).thenReturn(user);

        final Map<String, String> result = service.requestPasswordReset("{\"username\":\"ada\"}", "127.0.0.1");

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_REQUEST_MESSAGE, result.get("message"));
        verify(emailService, never()).sendDefinedEmail(any());
    }

    @Test
    void requestUserWithoutEmailReturnsGenericSuccessAndSendsNoEmail() {
        stubEligibleUserWithoutId();
        when(user.getEmail()).thenReturn("not-an-email");
        when(appUserRepository.findAppUserByName("ada")).thenReturn(user);

        final Map<String, String> result = service.requestPasswordReset("{\"username\":\"ada\"}", "127.0.0.1");

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_REQUEST_MESSAGE, result.get("message"));
        verify(emailService, never()).sendDefinedEmail(any());
    }

    @Test
    void requestValidUserStoresHashOnlyAndEmailsTenantBoundLink() {
        stubEligibleUser();
        stubWebAppBaseUrl();
        when(appUserRepository.findAppUserByName("ada")).thenReturn(user);
        when(passwordResetTokenRepository.countByAppUserIdAndCreatedOnUtcGreaterThanEqual(eq(1L), any())).thenReturn(0L);
        when(passwordResetTokenRepository.findFirstByAppUserIdOrderByCreatedOnUtcDesc(1L)).thenReturn(Optional.empty());
        when(passwordResetTokenRepository.findByAppUserIdAndConsumedOnUtcIsNull(1L)).thenReturn(List.of());

        final Map<String, String> result = service.requestPasswordReset("{\"username\":\"ada\"}", "127.0.0.1");

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_REQUEST_MESSAGE, result.get("message"));
        final ArgumentCaptor<AppUserPasswordResetToken> tokenCaptor = ArgumentCaptor.forClass(AppUserPasswordResetToken.class);
        verify(passwordResetTokenRepository).saveAndFlush(tokenCaptor.capture());
        final ArgumentCaptor<EmailDetail> emailCaptor = ArgumentCaptor.forClass(EmailDetail.class);
        verify(emailService).sendDefinedEmail(emailCaptor.capture());

        final String body = emailCaptor.getValue().getBody();
        assertTrue(body.contains("/#/reset-password?tenant=default&token="));
        final String rawToken = body.substring(body.indexOf("token=") + 6).split("\\s")[0];
        final AppUserPasswordResetToken stored = tokenCaptor.getValue();
        assertEquals(64, stored.getTokenHash().length());
        assertEquals(PasswordResetWritePlatformServiceImpl.hashToken(rawToken), stored.getTokenHash());
        assertNotEquals(rawToken, stored.getTokenHash());
        assertFalse(body.contains(stored.getTokenHash()));
    }

    @Test
    void requestValidUserStillReturnsGenericSuccessWhenEmailSendFails() {
        stubEligibleUser();
        stubWebAppBaseUrl();
        when(appUserRepository.findAppUserByName("ada")).thenReturn(user);
        when(passwordResetTokenRepository.countByAppUserIdAndCreatedOnUtcGreaterThanEqual(eq(1L), any())).thenReturn(0L);
        when(passwordResetTokenRepository.findFirstByAppUserIdOrderByCreatedOnUtcDesc(1L)).thenReturn(Optional.empty());
        when(passwordResetTokenRepository.findByAppUserIdAndConsumedOnUtcIsNull(1L)).thenReturn(List.of());
        org.mockito.Mockito.doThrow(new PlatformEmailSendException(new RuntimeException("smtp down"))).when(emailService)
                .sendDefinedEmail(any());

        final Map<String, String> result = service.requestPasswordReset("{\"username\":\"ada\"}", "127.0.0.1");

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_REQUEST_MESSAGE, result.get("message"));
    }

    @Test
    void requestOnSandboxTenantPutsSandboxInLink() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(2L, "sandbox", "Sandbox", "Asia/Kolkata", null));
        stubEligibleUser();
        stubWebAppBaseUrl();
        when(appUserRepository.findAppUserByName("ada")).thenReturn(user);
        when(passwordResetTokenRepository.countByAppUserIdAndCreatedOnUtcGreaterThanEqual(eq(1L), any())).thenReturn(0L);
        when(passwordResetTokenRepository.findFirstByAppUserIdOrderByCreatedOnUtcDesc(1L)).thenReturn(Optional.empty());
        when(passwordResetTokenRepository.findByAppUserIdAndConsumedOnUtcIsNull(1L)).thenReturn(List.of());

        service.requestPasswordReset("{\"username\":\"ada\"}", "127.0.0.1");

        final ArgumentCaptor<EmailDetail> emailCaptor = ArgumentCaptor.forClass(EmailDetail.class);
        verify(emailService).sendDefinedEmail(emailCaptor.capture());
        assertTrue(emailCaptor.getValue().getBody().contains("tenant=sandbox"));
        assertFalse(emailCaptor.getValue().getBody().contains("tenant=default"));
    }

    @Test
    void completeUnknownTokenIsGenericFailureAndDoesNotChangePassword() {
        stubPasswordPolicy();
        when(passwordResetTokenRepository.findByTokenHash(any())).thenReturn(Optional.empty());

        assertThrows(PasswordResetTokenInvalidException.class, () -> service.completePasswordReset(completeJson("missing-token")));
        verify(appUserRepository, never()).saveAndFlush(any());
    }

    @Test
    void completeExpiredTokenIsGenericFailure() {
        stubPasswordPolicy();
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final String rawToken = PasswordResetWritePlatformServiceImpl.generateRawToken();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user,
                PasswordResetWritePlatformServiceImpl.hashToken(rawToken), now.minus(2, ChronoUnit.HOURS), now.minus(1, ChronoUnit.HOURS),
                "127.0.0.1");
        when(passwordResetTokenRepository.findByTokenHash(token.getTokenHash())).thenReturn(Optional.of(token));

        assertThrows(PasswordResetTokenInvalidException.class, () -> service.completePasswordReset(completeJson(rawToken)));
        verify(appUserRepository, never()).saveAndFlush(any());
        assertFalse(token.isUsable(now));
    }

    @Test
    void completeReusedTokenIsGenericFailure() {
        stubPasswordPolicy();
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final String rawToken = PasswordResetWritePlatformServiceImpl.generateRawToken();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user,
                PasswordResetWritePlatformServiceImpl.hashToken(rawToken), now, now.plus(30, ChronoUnit.MINUTES), "127.0.0.1");
        token.consume(now);
        when(passwordResetTokenRepository.findByTokenHash(token.getTokenHash())).thenReturn(Optional.of(token));

        assertThrows(PasswordResetTokenInvalidException.class, () -> service.completePasswordReset(completeJson(rawToken)));
        verify(appUserRepository, never()).saveAndFlush(any());
    }

    @Test
    void completeWrongTenantTokenIsGenericFailure() {
        stubPasswordPolicy();
        when(passwordResetTokenRepository.findByTokenHash(any())).thenReturn(Optional.empty());

        final PasswordResetTokenInvalidException ex = assertThrows(PasswordResetTokenInvalidException.class,
                () -> service.completePasswordReset(completeJson("other-tenant-token")));
        assertEquals("This reset link is invalid or has expired.", ex.getDefaultUserMessage());
        verify(appUserRepository, never()).saveAndFlush(any());
    }

    @Test
    void completePasswordPolicyFailureLeavesTokenUsable() {
        when(passwordValidationPolicyRepository.findActivePasswordValidationPolicy()).thenReturn(passwordPolicy);
        when(passwordPolicy.getRegex()).thenReturn("^(?=.*[A-Z]).{12,}$");
        when(passwordPolicy.getDescription()).thenReturn("uppercase and 12 chars");

        assertThrows(PlatformApiDataValidationException.class,
                () -> service.completePasswordReset(completeJson("raw-token", "alllowercase1!", "alllowercase1!")));
        verify(passwordResetTokenRepository, never()).findByTokenHash(any());
        verify(appUserRepository, never()).saveAndFlush(any());
    }

    @Test
    void completeSameAsCurrentPasswordRecordsFailedAttemptAndKeepsToken() {
        stubPasswordPolicy();
        stubEligibleForComplete();
        when(user.getPassword()).thenReturn("encoded-current");
        when(platformPasswordEncoder.encode(any())).thenReturn("encoded-current");
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final String rawToken = PasswordResetWritePlatformServiceImpl.generateRawToken();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user,
                PasswordResetWritePlatformServiceImpl.hashToken(rawToken), now, now.plus(30, ChronoUnit.MINUTES), "127.0.0.1");
        when(passwordResetTokenRepository.findByTokenHash(token.getTokenHash())).thenReturn(Optional.of(token));

        assertThrows(PasswordSameAsCurrentException.class, () -> service.completePasswordReset(completeJson(rawToken)));
        assertEquals(1, token.getFailedAttemptCount());
        assertTrue(token.isUsable(DateUtils.getAuditOffsetDateTime()));
        verify(appUserRepository, never()).saveAndFlush(any());
        verify(passwordResetTokenRepository).saveAndFlush(token);
    }

    @Test
    void completeSuccessUpdatesPasswordAndConsumesToken() {
        stubPasswordPolicy();
        stubEligibleForComplete();
        when(user.getPassword()).thenReturn("encoded-old");
        when(platformPasswordEncoder.encode(any())).thenReturn("encoded-new");
        when(appUserPreviousPasswordRepository.findByUserId(eq(1L), any(Pageable.class))).thenReturn(List.of());
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final String rawToken = PasswordResetWritePlatformServiceImpl.generateRawToken();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user,
                PasswordResetWritePlatformServiceImpl.hashToken(rawToken), now, now.plus(30, ChronoUnit.MINUTES), "127.0.0.1");
        when(passwordResetTokenRepository.findByTokenHash(token.getTokenHash())).thenReturn(Optional.of(token));

        final Map<String, String> result = service.completePasswordReset(completeJson(rawToken));

        assertEquals(PasswordResetWritePlatformServiceImpl.GENERIC_COMPLETE_MESSAGE, result.get("message"));
        assertTrue(token.isConsumed());
        verify(user).updatePassword("encoded-new");
        verify(appUserRepository).saveAndFlush(user);
        verify(appUserPreviousPasswordRepository).save(any(AppUserPreviousPassword.class));
    }

    @Test
    void fiveFailedCompleteAttemptsBurnTheToken() {
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user, "abc", now, now.plus(30, ChronoUnit.MINUTES),
                "127.0.0.1");
        for (int i = 0; i < 4; i++) {
            token.recordFailedAttempt(now, PasswordResetWritePlatformServiceImpl.MAX_FAILED_ATTEMPTS);
            assertTrue(token.isUsable(now));
        }
        token.recordFailedAttempt(now, PasswordResetWritePlatformServiceImpl.MAX_FAILED_ATTEMPTS);
        assertFalse(token.isUsable(now));
        assertTrue(token.isConsumed());
    }

    private void stubEligibleUser() {
        when(user.getId()).thenReturn(1L);
        stubEligibleUserWithoutId();
        when(user.getEmail()).thenReturn("ada@example.com");
        when(user.getUsername()).thenReturn("ada");
        when(user.getFirstname()).thenReturn("Ada");
    }

    private void stubEligibleForComplete() {
        when(user.getId()).thenReturn(1L);
        stubEligibleUserWithoutId();
        when(user.getEmail()).thenReturn("ada@example.com");
        when(user.getUsername()).thenReturn("ada");
    }

    private void stubEligibleUserWithoutId() {
        when(user.isDeleted()).thenReturn(false);
        when(user.isEnabled()).thenReturn(true);
        when(user.isSystemUser()).thenReturn(false);
        when(user.canPasswordBeChanged()).thenReturn(true);
    }

    private void stubWebAppBaseUrl() {
        final FineractProperties.FineractWebAppProperties webapp = new FineractProperties.FineractWebAppProperties();
        webapp.setBaseUrl("http://localhost:4200");
        when(fineractProperties.getWebapp()).thenReturn(webapp);
    }

    private void stubPasswordPolicy() {
        when(passwordValidationPolicyRepository.findActivePasswordValidationPolicy()).thenReturn(passwordPolicy);
        when(passwordPolicy.getRegex()).thenReturn("^.{8,}$");
        when(passwordPolicy.getDescription()).thenReturn("at least 8 characters");
    }

    private static String completeJson(final String token) {
        return completeJson(token, "Password1!", "Password1!");
    }

    private static String completeJson(final String token, final String password, final String repeatPassword) {
        return "{\"token\":\"" + token + "\",\"password\":\"" + password + "\",\"repeatPassword\":\"" + repeatPassword + "\"}";
    }
}
