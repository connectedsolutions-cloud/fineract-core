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

import static org.apache.fineract.useradministration.service.AppUserConstants.PASSWORD;
import static org.apache.fineract.useradministration.service.AppUserConstants.REPEAT_PASSWORD;

import com.google.gson.JsonElement;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.config.FineractProperties;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.DataValidatorBuilder;
import org.apache.fineract.infrastructure.core.domain.EmailDetail;
import org.apache.fineract.infrastructure.core.exception.InvalidJsonException;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.service.PlatformEmailSendException;
import org.apache.fineract.infrastructure.core.service.PlatformEmailService;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.domain.BasicPasswordEncodablePlatformUser;
import org.apache.fineract.infrastructure.security.service.PlatformPasswordEncoder;
import org.apache.fineract.useradministration.api.AppUserApiConstant;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserPasswordResetToken;
import org.apache.fineract.useradministration.domain.AppUserPasswordResetTokenRepository;
import org.apache.fineract.useradministration.domain.AppUserPreviousPassword;
import org.apache.fineract.useradministration.domain.AppUserPreviousPasswordRepository;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.apache.fineract.useradministration.domain.PasswordValidationPolicy;
import org.apache.fineract.useradministration.domain.PasswordValidationPolicyRepository;
import org.apache.fineract.useradministration.exception.PasswordPreviouslyUsedException;
import org.apache.fineract.useradministration.exception.PasswordResetTokenInvalidException;
import org.apache.fineract.useradministration.exception.PasswordSameAsCurrentException;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Caching;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class PasswordResetWritePlatformServiceImpl implements PasswordResetWritePlatformService {

    public static final String GENERIC_REQUEST_MESSAGE = "If an account exists for that username, we sent a password reset link.";
    public static final String GENERIC_COMPLETE_MESSAGE = "Your password has been reset. You can now sign in.";

    static final int TOKEN_TTL_MINUTES = 30;
    static final int MIN_REQUEST_INTERVAL_SECONDS = 60;
    static final int MAX_REQUESTS_PER_HOUR = 5;
    static final int MAX_FAILED_ATTEMPTS = 5;
    private static final int TOKEN_BYTES = 32;
    private static final String USERNAME_PARAM = "username";
    private static final String TOKEN_PARAM = "token";
    private static final Set<String> REQUEST_PARAMETERS = new HashSet<>(List.of(USERNAME_PARAM));
    private static final Set<String> COMPLETE_PARAMETERS = new HashSet<>(Arrays.asList(TOKEN_PARAM, PASSWORD, REPEAT_PASSWORD));
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    private final FromJsonHelper fromApiJsonHelper;
    private final AppUserRepository appUserRepository;
    private final AppUserPasswordResetTokenRepository passwordResetTokenRepository;
    private final PasswordValidationPolicyRepository passwordValidationPolicyRepository;
    private final AppUserPreviousPasswordRepository appUserPreviousPasswordRepository;
    private final PlatformPasswordEncoder platformPasswordEncoder;
    private final PlatformEmailService emailService;
    private final FineractProperties fineractProperties;

    @Override
    @Transactional
    public Map<String, String> requestPasswordReset(final String apiRequestBodyAsJson, final String remoteAddress) {
        final String username = extractUsername(apiRequestBodyAsJson);
        hashToken(generateRawToken());
        final AppUser user = this.appUserRepository.findAppUserByName(username);
        if (isEligible(user)) {
            issueTokenIfAllowed(user, remoteAddress);
        }
        return Map.of("message", GENERIC_REQUEST_MESSAGE);
    }

    @Override
    @Transactional
    @Caching(evict = { @CacheEvict(value = "users", allEntries = true), @CacheEvict(value = "usersByUsername", allEntries = true) })
    public Map<String, String> completePasswordReset(final String apiRequestBodyAsJson) {
        if (StringUtils.isBlank(apiRequestBodyAsJson)) {
            throw new InvalidJsonException();
        }
        final Type typeOfMap = new TypeToken<Map<String, Object>>() {}.getType();
        this.fromApiJsonHelper.checkForUnsupportedParameters(typeOfMap, apiRequestBodyAsJson, COMPLETE_PARAMETERS);
        final JsonElement element = this.fromApiJsonHelper.parse(apiRequestBodyAsJson);
        final String rawToken = this.fromApiJsonHelper.extractStringNamed(TOKEN_PARAM, element);
        final String password = this.fromApiJsonHelper.extractStringNamed(PASSWORD, element);
        final String repeatPassword = this.fromApiJsonHelper.extractStringNamed(REPEAT_PASSWORD, element);

        final List<ApiParameterError> dataValidationErrors = new ArrayList<>();
        final DataValidatorBuilder baseDataValidator = new DataValidatorBuilder(dataValidationErrors).resource("passwordreset");
        baseDataValidator.reset().parameter(TOKEN_PARAM).value(rawToken).notBlank();
        validatePassword(baseDataValidator, password, repeatPassword);
        baseDataValidator.throwValidationErrors();

        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final AppUserPasswordResetToken resetToken = this.passwordResetTokenRepository.findByTokenHash(hashToken(rawToken)).orElse(null);
        if (resetToken == null || !resetToken.isUsable(now)) {
            throw new PasswordResetTokenInvalidException();
        }
        final AppUser user = resetToken.getAppUser();
        if (!isEligible(user)) {
            resetToken.consume(now);
            this.passwordResetTokenRepository.saveAndFlush(resetToken);
            throw new PasswordResetTokenInvalidException();
        }
        try {
            applyNewPassword(user, password);
        } catch (final PlatformApiDataValidationException ex) {
            resetToken.recordFailedAttempt(now, MAX_FAILED_ATTEMPTS);
            this.passwordResetTokenRepository.saveAndFlush(resetToken);
            throw ex;
        }
        resetToken.consume(now);
        this.passwordResetTokenRepository.saveAndFlush(resetToken);
        return Map.of("message", GENERIC_COMPLETE_MESSAGE);
    }

    private String extractUsername(final String apiRequestBodyAsJson) {
        if (StringUtils.isBlank(apiRequestBodyAsJson)) {
            throw new InvalidJsonException();
        }
        final Type typeOfMap = new TypeToken<Map<String, Object>>() {}.getType();
        this.fromApiJsonHelper.checkForUnsupportedParameters(typeOfMap, apiRequestBodyAsJson, REQUEST_PARAMETERS);
        final JsonElement element = this.fromApiJsonHelper.parse(apiRequestBodyAsJson);
        final String username = this.fromApiJsonHelper.extractStringNamed(USERNAME_PARAM, element);
        final List<ApiParameterError> dataValidationErrors = new ArrayList<>();
        final DataValidatorBuilder baseDataValidator = new DataValidatorBuilder(dataValidationErrors).resource("passwordreset");
        baseDataValidator.reset().parameter(USERNAME_PARAM).value(username).notBlank().notExceedingLengthOf(100);
        baseDataValidator.throwValidationErrors();
        return username.trim();
    }

    private boolean isEligible(final AppUser user) {
        if (user == null || user.isDeleted() || !user.isEnabled() || user.isSystemUser() || !user.canPasswordBeChanged()) {
            return false;
        }
        final String email = user.getEmail();
        return StringUtils.isNotBlank(email) && email.contains("@");
    }

    private void issueTokenIfAllowed(final AppUser user, final String remoteAddress) {
        final OffsetDateTime now = DateUtils.getAuditOffsetDateTime();
        final long requestsLastHour = this.passwordResetTokenRepository.countByAppUserIdAndCreatedOnUtcGreaterThanEqual(user.getId(),
                now.minus(1, ChronoUnit.HOURS));
        if (requestsLastHour >= MAX_REQUESTS_PER_HOUR) {
            log.debug("Password reset rate-limited for user id {}", user.getId());
            return;
        }
        final boolean tooSoon = this.passwordResetTokenRepository.findFirstByAppUserIdOrderByCreatedOnUtcDesc(user.getId())
                .filter(latest -> latest.getCreatedOnUtc() != null
                        && latest.getCreatedOnUtc().isAfter(now.minus(MIN_REQUEST_INTERVAL_SECONDS, ChronoUnit.SECONDS)))
                .isPresent();
        if (tooSoon) {
            log.debug("Password reset requested too soon for user id {}", user.getId());
            return;
        }
        for (final AppUserPasswordResetToken previous : this.passwordResetTokenRepository
                .findByAppUserIdAndConsumedOnUtcIsNull(user.getId())) {
            previous.consume(now);
            this.passwordResetTokenRepository.save(previous);
        }
        final String rawToken = generateRawToken();
        final AppUserPasswordResetToken token = AppUserPasswordResetToken.create(user, hashToken(rawToken), now,
                now.plus(TOKEN_TTL_MINUTES, ChronoUnit.MINUTES), StringUtils.abbreviate(remoteAddress, 45));
        this.passwordResetTokenRepository.saveAndFlush(token);
        sendResetEmail(user, rawToken);
    }

    private void sendResetEmail(final AppUser user, final String rawToken) {
        final String baseUrl = this.fineractProperties.getWebapp() == null ? null : this.fineractProperties.getWebapp().getBaseUrl();
        if (StringUtils.isBlank(baseUrl)) {
            log.error("Password reset email skipped: fineract.webapp.base-url is not configured");
            return;
        }
        String origin = baseUrl.trim();
        while (origin.endsWith("/")) {
            origin = origin.substring(0, origin.length() - 1);
        }
        final String tenantId = ThreadLocalContextUtil.getTenant() == null ? "" : ThreadLocalContextUtil.getTenant().getTenantIdentifier();
        final String link = origin + "/#/reset-password?tenant=" + tenantId + "&token=" + rawToken;
        final String contactName = StringUtils.defaultIfBlank(user.getFirstname(), user.getUsername());
        final String subject = "Restablecer contraseña / Password reset";
        final String body = "Hola " + contactName + ",\n\nRecibimos una solicitud para restablecer la contraseña de la cuenta "
                + user.getUsername() + ".\nUse este enlace (válido por " + TOKEN_TTL_MINUTES + " minutos):\n" + link
                + "\n\nSi usted no solicitó este cambio, ignore este correo.\n";
        try {
            this.emailService.sendDefinedEmail(new EmailDetail(subject, body, user.getEmail(), contactName));
        } catch (final PlatformEmailSendException ex) {
            log.error("Failed to send password reset email for user id {}", user.getId(), ex);
        } catch (final RuntimeException ex) {
            log.error("Unexpected error sending password reset email for user id {}", user.getId(), ex);
        }
    }

    private void validatePassword(final DataValidatorBuilder baseDataValidator, final String password, final String repeatPassword) {
        final PasswordValidationPolicy validationPolicy = this.passwordValidationPolicyRepository.findActivePasswordValidationPolicy();
        final String regex = validationPolicy.getRegex();
        final String description = validationPolicy.getDescription();
        final DataValidatorBuilder validator = baseDataValidator.reset().parameter(PASSWORD).value(password).matchesRegularExpression(regex,
                description);
        if (StringUtils.isNotBlank(password)) {
            validator.equalToParameter(REPEAT_PASSWORD, repeatPassword);
        }
    }

    private void applyNewPassword(final AppUser user, final String rawPassword) {
        final BasicPasswordEncodablePlatformUser dummyUser = new BasicPasswordEncodablePlatformUser().setId(user.getId())
                .setUsername(user.getUsername()).setPassword(rawPassword);
        final String encodedPassword = this.platformPasswordEncoder.encode(dummyUser);
        if (encodedPassword.equals(user.getPassword())) {
            throw new PasswordSameAsCurrentException();
        }
        final PageRequest pageRequest = PageRequest.of(0, AppUserApiConstant.numberOfPreviousPasswords, Sort.Direction.DESC, "removalDate");
        final List<AppUserPreviousPassword> previousPasswords = this.appUserPreviousPasswordRepository.findByUserId(user.getId(),
                pageRequest);
        for (final AppUserPreviousPassword previousPassword : previousPasswords) {
            if (encodedPassword.equals(previousPassword.getPassword())) {
                throw new PasswordPreviouslyUsedException();
            }
        }
        this.appUserPreviousPasswordRepository.save(new AppUserPreviousPassword(user));
        user.updatePassword(encodedPassword);
        this.appUserRepository.saveAndFlush(user);
    }

    static String generateRawToken() {
        final byte[] bytes = new byte[TOKEN_BYTES];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    static String hashToken(final String rawToken) {
        try {
            final MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(rawToken.getBytes(StandardCharsets.UTF_8)));
        } catch (final NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is required for password reset tokens", ex);
        }
    }
}
