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
package org.apache.fineract.portfolio.shareaccounts.service;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.namingsequence.service.CredesalNamingSequenceService;
import org.apache.fineract.portfolio.namingsequence.service.ShareSerialAllocation;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccount;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountRepositoryWrapper;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountTransaction;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificate;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificateBeneficiary;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificateRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ShareCertificateService {

    private final ShareCertificateRepository certificateRepository;
    private final ShareAccountRepositoryWrapper shareAccountRepository;
    private final CredesalNamingSequenceService namingSequenceService;
    private final FromJsonHelper fromApiJsonHelper;

    @Transactional
    public void openFirstCertificate(final ShareAccount account, final JsonCommand command) {
        final JsonElement element = command.jsonElement("shareCertificate");
        if (element == null || element.isJsonNull()) {
            return;
        }
        final Long requestedShares = command.longValueOfParameterNamed("requestedShares");
        if (requestedShares == null) {
            throw validation("requestedShares", "Certificate quantity must be at least 1.");
        }
        final long quantity = requestedShares;
        final String reservationKey = "share-certificate:" + account.getClient().getId() + ":" + account.getShareProduct().getId();
        open(account, element.getAsJsonObject(), quantity, reservationKey, false);
    }

    @Transactional
    public CommandProcessingResult openAdditional(final Long shareAccountId, final String json) {
        final ShareAccount account = this.shareAccountRepository.findOneWithNotFoundDetection(shareAccountId);
        final JsonObject body = this.fromApiJsonHelper.parse(json).getAsJsonObject();
        final long quantity = requiredLong(body, "requestedShares");
        final String reservationKey = "share-certificate-additional:" + shareAccountId + ":" + quantity + ":" + body.get("folio") + ":"
                + body.get("lineNumber");
        final ShareCertificate certificate = open(account, body, quantity, reservationKey, true);
        return new CommandProcessingResultBuilder().withEntityId(certificate.getId()).withClientId(account.getClient().getId()).build();
    }

    @Transactional
    public void reopenUnprinted(final Long shareAccountId) {
        final List<ShareCertificate> certificates = this.certificateRepository.findByShareAccountIdOrderByIdAsc(shareAccountId);
        for (final ShareCertificate certificate : certificates) {
            if (Boolean.TRUE.equals(certificate.getPrinted())) {
                throw validation("printed", "A printed share certificate cannot be returned to approved.");
            }
        }
        for (final ShareCertificate certificate : certificates) {
            if (ShareCertificate.STATUS_ISSUED.equals(certificate.getNativeStatus())) {
                certificate.setNativeStatus(ShareCertificate.STATUS_OPENED);
                certificate.setCertificateNumber(null);
                certificate.setUpdatedAt(LocalDateTime.now());
                this.certificateRepository.save(certificate);
            }
        }
    }

    @Transactional
    public CommandProcessingResult emit(final Long certificateId) {
        final ShareCertificate certificate = certificate(certificateId);
        if (!ShareCertificate.STATUS_OPENED.equals(certificate.getNativeStatus())) {
            throw validation("nativeStatus", "Only an opened certificate can be emitted.");
        }
        final String numberingCode = certificate.getShareClassCode();
        final String number = this.namingSequenceService.allocateShareCertificateNumber(certificate.getClient(), numberingCode,
                "share-certificate-emit:" + certificate.getId());
        certificate.setCertificateNumber(number);
        certificate.setNativeStatus(ShareCertificate.STATUS_ISSUED);
        if (certificate.getCertificateDate() == null) {
            certificate.setCertificateDate(DateUtils.getBusinessLocalDate());
        }
        certificate.setUpdatedAt(LocalDateTime.now());
        this.certificateRepository.save(certificate);
        return new CommandProcessingResultBuilder().withEntityId(certificate.getId()).withClientId(certificate.getClient().getId()).build();
    }

    @Transactional
    public CommandProcessingResult markPrinted(final Long certificateId) {
        final ShareCertificate certificate = certificate(certificateId);
        certificate.setPrinted(true);
        certificate.setPrintedAt(LocalDateTime.now());
        certificate.setUpdatedAt(LocalDateTime.now());
        this.certificateRepository.save(certificate);
        return new CommandProcessingResultBuilder().withEntityId(certificate.getId()).build();
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> listByShareAccount(final Long shareAccountId) {
        final ShareAccount account = this.shareAccountRepository.findOneWithNotFoundDetection(shareAccountId);
        return toMaps(this.certificateRepository.findByShareAccountIdOrderByIdAsc(shareAccountId), account.getTotalApprovedShares());
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> summariesByClient(final Long clientId) {
        final Map<Long, List<ShareCertificate>> byAccount = new LinkedHashMap<>();
        for (final ShareCertificate certificate : this.certificateRepository.findByClientIdOrderByIdAsc(clientId)) {
            if (certificate.getShareAccount() == null) {
                continue;
            }
            byAccount.computeIfAbsent(certificate.getShareAccount().getId(), ignored -> new ArrayList<>()).add(certificate);
        }
        final List<Map<String, Object>> summaries = new ArrayList<>();
        for (final Map.Entry<Long, List<ShareCertificate>> entry : byAccount.entrySet()) {
            final List<ShareCertificate> certificates = entry.getValue();
            final Map<String, Object> summary = new LinkedHashMap<>();
            summary.put("shareAccountId", entry.getKey());
            summary.put("certificateCount", certificates.size());
            summary.put("displayNumber", certificates.size() == 1 ? displayNumber(certificates.get(0)) : null);
            summaries.add(summary);
        }
        return summaries;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> printPayload(final Long certificateId) {
        final ShareCertificate certificate = certificate(certificateId);
        final Long approved = certificate.getShareAccount() == null ? 0L : certificate.getShareAccount().getTotalApprovedShares();
        final List<ShareCertificate> siblings = certificate.getShareAccount() == null ? List.of(certificate)
                : this.certificateRepository.findByShareAccountIdOrderByIdAsc(certificate.getShareAccount().getId());
        return toMap(certificate, paidShares(siblings, approved).getOrDefault(certificate.getId(), 0L));
    }

    private ShareCertificate open(final ShareAccount account, final JsonObject body, final long quantity, final String reservationKey,
            final boolean limitToUncoveredShares) {
        if (quantity < 1) {
            throw validation("requestedShares", "Certificate quantity must be at least 1.");
        }
        final String numberingCode = account.getShareProduct().getNumberingCode();
        if (!"1AC".equals(numberingCode) && !"1AP".equals(numberingCode)) {
            throw validation("productId", "The share product needs numbering code 1AC or 1AP before a certificate can be opened.");
        }
        final int folio = requiredInt(body, "folio");
        final int lineNumber = requiredInt(body, "lineNumber");
        final String series = requiredText(body, "series");
        final String bookNumber = requiredText(body, "bookNumber");
        final LocalDate bookDate = requiredDate(body, "bookDate");
        // Fineract uses logical book IDs by share class. Arissto's preferred certificate links are inconsistent
        // with its separate preferred "No. 2" book configuration, so those source links are preserved in the archive.
        final int bookId = "1AC".equals(numberingCode) ? 1 : 2;
        if (!bookNumber.equals("No. " + bookId)) {
            throw validation("bookNumber", "The book number must match the share class.");
        }
        if (this.certificateRepository.existsBySourceSystemAndBookIdAndFolioAndLineNumber(ShareCertificate.SOURCE_FINERACT, bookId, folio,
                lineNumber)) {
            throw validation("folio", "That folio and line are already used in this share book.");
        }
        if (limitToUncoveredShares) {
            final long covered = this.certificateRepository.findByShareAccountIdOrderByIdAsc(account.getId()).stream()
                    .map(ShareCertificate::getRepresentedShares).filter(value -> value != null).mapToLong(BigDecimal::longValue).sum();
            final long approved = account.getTotalApprovedShares() == null ? 0L : account.getTotalApprovedShares();
            if (quantity > approved - covered) {
                throw validation("requestedShares", "Certificate quantity exceeds approved shares that are not already on a certificate.");
            }
        }
        final List<ShareCertificateBeneficiary> beneficiaries = beneficiaries(body, reservationKey);
        final String provisional = this.namingSequenceService.allocateProvisionalShareCertificateNumber(reservationKey);
        final ShareSerialAllocation serials = this.namingSequenceService.allocateShareSerialRange(numberingCode, (int) quantity,
                reservationKey);
        final BigDecimal unitPrice = account.getShareProduct().deriveMarketPrice(DateUtils.getBusinessLocalDate());
        if (unitPrice == null) {
            throw validation("unitPrice", "The share product does not have a unit price for this date.");
        }
        final LocalDateTime now = LocalDateTime.now();
        final ShareCertificate certificate = new ShareCertificate();
        certificate.setSourceSystem(ShareCertificate.SOURCE_FINERACT);
        certificate.setSourceKey("fineract:share-certificate:" + account.getId() + ":" + provisional);
        certificate.setSourceHash(sha256(certificate.getSourceKey()));
        certificate.setClient(account.getClient());
        certificate.setShareAccount(account);
        certificate.setShareClassCode(numberingCode);
        certificate.setShareTypeName("1AC".equals(numberingCode) ? "ACCIONES COMUNES" : "ACCIONES PREFERIDAS");
        certificate.setNativeStatus(ShareCertificate.STATUS_OPENED);
        certificate.setOfficeId(account.getOfficeId());
        if (body.has("promoterStaffId") && !body.get("promoterStaffId").isJsonNull()
                && StringUtils.isNotBlank(body.get("promoterStaffId").getAsString())) {
            certificate.setPromoterStaffId(Long.valueOf(body.get("promoterStaffId").getAsString()));
        }
        certificate.setBookId(bookId);
        certificate.setProvisionalNumber(provisional);
        certificate.setCertificateDate(certificateDate(account));
        certificate.setUnitPrice(unitPrice);
        certificate.setRepresentedShares(BigDecimal.valueOf(quantity));
        certificate.setSubscribedShares(BigDecimal.valueOf(quantity));
        certificate.setSubscribedBalance(unitPrice.multiply(BigDecimal.valueOf(quantity)).setScale(2, RoundingMode.HALF_UP));
        certificate.setPaidShares(BigDecimal.ZERO);
        certificate.setPaidBalance(BigDecimal.ZERO);
        certificate.setShareSerialStart(serials.startInclusive());
        certificate.setShareSerialEnd(serials.endInclusive());
        certificate.setInitialShareNumber(Long.toString(serials.startInclusive()));
        certificate.setFinalShareNumber(Long.toString(serials.endInclusive()));
        certificate.setFolio(folio);
        certificate.setLineNumber(lineNumber);
        certificate.setSeries(series);
        certificate.setBookNumber(bookNumber);
        certificate.setBookDate(bookDate);
        certificate.setCurrentBalance(BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP));
        certificate.setPledgedBalance(BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP));
        certificate.setPrinted(false);
        certificate.setCreatedAt(now);
        certificate.setUpdatedAt(now);
        beneficiaries.forEach(certificate::addBeneficiary);
        return this.certificateRepository.save(certificate);
    }

    private List<ShareCertificateBeneficiary> beneficiaries(final JsonObject body, final String reservationKey) {
        if (!body.has("beneficiaries") || body.get("beneficiaries").isJsonNull()) {
            return List.of();
        }
        final JsonArray rows = body.getAsJsonArray("beneficiaries");
        if (rows.isEmpty()) {
            return List.of();
        }
        final String dateFormat = text(body, "dateFormat", "yyyy-MM-dd");
        final String locale = text(body, "locale", "en");
        final List<ShareCertificateBeneficiary> beneficiaries = new ArrayList<>();
        BigDecimal total = BigDecimal.ZERO;
        int index = 0;
        for (final JsonElement element : rows) {
            final JsonObject row = element.getAsJsonObject();
            final ShareCertificateBeneficiary beneficiary = new ShareCertificateBeneficiary();
            beneficiary.setSourceSystem(ShareCertificate.SOURCE_FINERACT);
            beneficiary.setSourceKey(reservationKey + ":beneficiary:" + index);
            beneficiary.setSourceHash(sha256(beneficiary.getSourceKey()));
            beneficiary.setFirstNames(text(row, "firstNames", null));
            beneficiary.setLastNames(text(row, "lastNames", null));
            beneficiary.setRelationship(text(row, "relationship", null));
            beneficiary.setAddress(text(row, "address", null));
            beneficiary.setPhone(text(row, "phone", null));
            if (StringUtils.isBlank(beneficiary.getFirstNames()) && StringUtils.isBlank(beneficiary.getLastNames())) {
                throw validation("beneficiaries", "Each beneficiary needs a name.");
            }
            if (!row.has("percentage") || row.get("percentage").isJsonNull() || StringUtils.isBlank(row.get("percentage").getAsString())) {
                throw validation("percentage", "Each beneficiary needs a percentage.");
            }
            final BigDecimal percentage = new BigDecimal(row.get("percentage").getAsString());
            beneficiary.setPercentage(percentage);
            total = total.add(percentage);
            if (row.has("dateOfBirth") && !row.get("dateOfBirth").isJsonNull()
                    && StringUtils.isNotBlank(row.get("dateOfBirth").getAsString())) {
                beneficiary.setDateOfBirth(
                        this.fromApiJsonHelper.extractLocalDateNamed("dateOfBirth", row, dateFormat, Locale.forLanguageTag(locale)));
            }
            beneficiary.setNotifyDesignation(row.has("notifyDesignation") && !row.get("notifyDesignation").isJsonNull()
                    && row.get("notifyDesignation").getAsBoolean());
            beneficiary.setCreatedAt(LocalDateTime.now());
            beneficiaries.add(beneficiary);
            index++;
        }
        if (total.compareTo(new BigDecimal("100")) != 0) {
            throw validation("percentage", "Beneficiary percentages must total 100.");
        }
        return beneficiaries;
    }

    private ShareCertificate certificate(final Long certificateId) {
        return this.certificateRepository.findById(certificateId).orElseThrow(
                () -> new PlatformDataIntegrityException("error.msg.share.certificate.not.found", "Share certificate not found."));
    }

    private List<Map<String, Object>> toMaps(final List<ShareCertificate> certificates, final Long approvedShares) {
        final Map<Long, Long> paid = paidShares(certificates, approvedShares);
        final List<Map<String, Object>> rows = new ArrayList<>();
        for (final ShareCertificate certificate : certificates) {
            rows.add(toMap(certificate, paid.getOrDefault(certificate.getId(), 0L)));
        }
        return rows;
    }

    private Map<String, Object> toMap(final ShareCertificate certificate, final long paidShareCount) {
        final Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", certificate.getId());
        row.put("shareAccountId", certificate.getShareAccount() == null ? null : certificate.getShareAccount().getId());
        row.put("clientId", certificate.getClient().getId());
        row.put("shareClassCode", certificate.getShareClassCode());
        row.put("shareTypeName", certificate.getShareTypeName());
        row.put("provisionalNumber", certificate.getProvisionalNumber());
        row.put("certificateNumber", certificate.getCertificateNumber());
        row.put("displayNumber", displayNumber(certificate));
        row.put("status", displayStatus(certificate, paidShareCount));
        row.put("certificateDate", certificate.getCertificateDate());
        row.put("representedShares", certificate.getRepresentedShares());
        row.put("shareSerialStart",
                certificate.getShareSerialStart() == null ? certificate.getInitialShareNumber() : certificate.getShareSerialStart());
        row.put("shareSerialEnd",
                certificate.getShareSerialEnd() == null ? certificate.getFinalShareNumber() : certificate.getShareSerialEnd());
        row.put("unitPrice", certificate.getUnitPrice());
        row.put("subscribedShares", certificate.getSubscribedShares());
        row.put("subscribedBalance", certificate.getSubscribedBalance());
        row.put("paidShares", paidShareCount);
        row.put("folio", certificate.getFolio());
        row.put("lineNumber", certificate.getLineNumber());
        row.put("bookId", certificate.getBookId());
        row.put("series", certificate.getSeries());
        row.put("bookNumber", certificate.getBookNumber());
        row.put("bookDate", certificate.getBookDate());
        row.put("currentBalance", certificate.getCurrentBalance());
        row.put("pledgedBalance", certificate.getPledgedBalance());
        row.put("promoterStaffId", certificate.getPromoterStaffId());
        row.put("officeId", certificate.getOfficeId());
        row.put("printed", Boolean.TRUE.equals(certificate.getPrinted()));
        final List<Map<String, Object>> beneficiaries = new ArrayList<>();
        for (final ShareCertificateBeneficiary beneficiary : certificate.getBeneficiaries()) {
            final Map<String, Object> item = new LinkedHashMap<>();
            item.put("firstNames", beneficiary.getFirstNames());
            item.put("lastNames", beneficiary.getLastNames());
            item.put("relationship", beneficiary.getRelationship());
            item.put("percentage", beneficiary.getPercentage());
            item.put("address", beneficiary.getAddress());
            item.put("phone", beneficiary.getPhone());
            item.put("dateOfBirth", beneficiary.getDateOfBirth());
            item.put("notifyDesignation", Boolean.TRUE.equals(beneficiary.getNotifyDesignation()));
            beneficiaries.add(item);
        }
        row.put("beneficiaries", beneficiaries);
        return row;
    }

    private static Map<Long, Long> paidShares(final List<ShareCertificate> certificates, final Long approvedShares) {
        long remaining = approvedShares == null ? 0L : approvedShares;
        final Map<Long, Long> paid = new LinkedHashMap<>();
        for (final ShareCertificate certificate : certificates) {
            final long represented = certificate.getRepresentedShares() == null ? 0L : certificate.getRepresentedShares().longValue();
            final long covered = Math.min(represented, Math.max(remaining, 0L));
            remaining -= covered;
            paid.put(certificate.getId(), covered);
        }
        return paid;
    }

    private static String displayNumber(final ShareCertificate certificate) {
        return StringUtils.defaultIfBlank(certificate.getCertificateNumber(), certificate.getProvisionalNumber());
    }

    private static String displayStatus(final ShareCertificate certificate, final long paidShareCount) {
        if (ShareCertificate.STATUS_ISSUED.equals(certificate.getNativeStatus()) && certificate.getRepresentedShares() != null
                && paidShareCount >= certificate.getRepresentedShares().longValue()) {
            return ShareCertificate.STATUS_PAID;
        }
        if (StringUtils.isNotBlank(certificate.getNativeStatus())) {
            return certificate.getNativeStatus();
        }
        return certificate.getStatusName();
    }

    private static LocalDate certificateDate(final ShareAccount account) {
        if (account.getShareAccountTransactions() != null) {
            for (final ShareAccountTransaction transaction : account.getShareAccountTransactions()) {
                if (transaction.isPendingForApprovalTransaction() && transaction.getPurchasedDate() != null) {
                    return transaction.getPurchasedDate();
                }
            }
        }
        return account.getSubmittedDate() != null ? account.getSubmittedDate() : DateUtils.getBusinessLocalDate();
    }

    private LocalDate requiredDate(final JsonObject body, final String name) {
        if (!body.has(name) || body.get(name).isJsonNull() || StringUtils.isBlank(body.get(name).getAsString())) {
            throw validation(name, name + " is required.");
        }
        final String dateFormat = text(body, "dateFormat", "yyyy-MM-dd");
        final String locale = text(body, "locale", "en");
        return this.fromApiJsonHelper.extractLocalDateNamed(name, body, dateFormat, Locale.forLanguageTag(locale));
    }

    private static String requiredText(final JsonObject body, final String name) {
        final String value = text(body, name, null);
        if (StringUtils.isBlank(value)) {
            throw validation(name, name + " is required.");
        }
        return value;
    }

    private static int requiredInt(final JsonObject body, final String name) {
        return (int) requiredLong(body, name);
    }

    private static long requiredLong(final JsonObject body, final String name) {
        if (!body.has(name) || body.get(name).isJsonNull() || StringUtils.isBlank(body.get(name).getAsString())) {
            throw validation(name, name + " is required.");
        }
        return Long.parseLong(body.get(name).getAsString());
    }

    private static String text(final JsonObject body, final String name, final String fallback) {
        if (!body.has(name) || body.get(name).isJsonNull()) {
            return fallback;
        }
        final String value = body.get(name).getAsString();
        return StringUtils.isBlank(value) ? fallback : value.trim();
    }

    private static PlatformApiDataValidationException validation(final String parameter, final String message) {
        return new PlatformApiDataValidationException(
                List.of(ApiParameterError.parameterError("validation.msg.share.certificate." + parameter, message, parameter)));
    }

    private static String sha256(final String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (final NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
