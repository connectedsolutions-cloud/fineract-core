/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor
 * license agreements. See the NOTICE file distributed with this work for
 * additional information regarding copyright ownership. The ASF licenses this
 * file to you under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain a
 * copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.accounting.journalentry.service;

import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.accounting.journalentry.domain.GlAuxiliar;
import org.apache.fineract.accounting.journalentry.domain.GlAuxiliarRepository;
import org.apache.fineract.accounting.journalentry.domain.GlVoucher;
import org.apache.fineract.accounting.journalentry.domain.GlVoucherRepository;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.springframework.stereotype.Service;

/** Creates voucher metadata in the caller's journal-posting transaction. */
@Service
@RequiredArgsConstructor
public class GlVoucherWriteService {

    private static final String NATIVE_RULE_VERSION = "2026-10-12-v1";

    private final GlVoucherRepository voucherRepository;
    private final GlAuxiliarRepository auxiliarRepository;

    public GlVoucher createManual(String auxiliarCode, String headerConcept) {
        if (StringUtils.isBlank(auxiliarCode) || StringUtils.isBlank(headerConcept)) {
            throw new GeneralPlatformDomainRuleException("error.msg.gl.voucher.manual.metadata.required",
                    "Manual journals require an Auxiliar and header concept");
        }
        GlAuxiliar auxiliar = auxiliarRepository.findById(auxiliarCode.trim())
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.gl.voucher.manual.auxiliar.unknown",
                        "Unknown manual journal Auxiliar"));
        if (!auxiliar.isActive() || !auxiliar.isManualAllowed()) {
            throw new GeneralPlatformDomainRuleException("error.msg.gl.voucher.manual.auxiliar.not.approved",
                    "The selected Auxiliar is not approved for manual journals");
        }
        return voucherRepository
                .saveAndFlush(GlVoucher.create(auxiliar.getCode(), headerConcept, "MANUAL", "MANUAL_JOURNAL", null, null, null));
    }

    public GlVoucher createHistorical(String sourceModuleCode, String sourceHeaderConcept, String sourceHeaderDescription,
            String sourceJournalId, String sourceJournalType) {
        String code = StringUtils.trimToNull(sourceModuleCode);
        // An unexpected source code must not make an otherwise eligible GL journal unimportable.
        // The exact code remains in restricted Arissto provenance for review.
        if (code != null && !auxiliarRepository.existsById(code)) {
            code = null;
        }
        String concept = StringUtils.firstNonBlank(sourceHeaderConcept, sourceHeaderDescription);
        GlVoucher voucher = GlVoucher.create(code, concept, "ARISSTO_HISTORICAL_GL_IMPORT", "HISTORICAL_JOURNAL",
                "ARISSTO_JOURNAL", sourceJournalId, null);
        if ("003".equals(sourceJournalType)) {
            voucher.markAnnualClosing();
        }
        return voucherRepository.saveAndFlush(voucher);
    }

    /** Classify a native group by the approved posting route, never by its account or free-text description. */
    public GlVoucher createNative(String operationType, String headerConcept, String sourceEntityType, String sourceEntityId) {
        if (StringUtils.isBlank(operationType) || StringUtils.isBlank(headerConcept) || StringUtils.isBlank(sourceEntityType)
                || StringUtils.isBlank(sourceEntityId)) {
            throw new IllegalArgumentException("Native voucher route, concept and source pointer are required");
        }
        NativeRouteRule rule = switch (operationType) {
            case "TELLER_ALLOCATE", "TELLER_SETTLE" -> new NativeRouteRule("3", "CASHIER_TRANSACTION");
            case "TELLER_TO_VAULT", "VAULT_TO_TELLER" -> new NativeRouteRule("20", "TELLER_VAULT_TRANSFER");
            case "COMITE_VAULT_RECEPTION" -> new NativeRouteRule("20", "COMITE_SESSION");
            case "COMITE_CASHIER_RECEPTION" -> new NativeRouteRule("3", "COMITE_SESSION");
            case "COMITE_DISBURSEMENT_CLEARING" -> new NativeRouteRule("4", "COMITE_SESSION");
            default -> throw new GeneralPlatformDomainRuleException("error.msg.gl.voucher.native.route.unmapped",
                    "No approved Auxiliar rule exists for native posting route " + operationType);
        };
        if (!rule.sourceEntityType().equals(sourceEntityType)) {
            throw new GeneralPlatformDomainRuleException("error.msg.gl.voucher.native.source.type.invalid",
                    "The native voucher source type does not match its posting route");
        }
        GlAuxiliar auxiliar = auxiliarRepository.findById(rule.auxiliarCode())
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.gl.voucher.native.auxiliar.missing",
                        "The approved native Auxiliar code is missing from the catalog"));
        if (!auxiliar.isActive()) {
            throw new GeneralPlatformDomainRuleException("error.msg.gl.voucher.native.auxiliar.inactive",
                    "The approved native Auxiliar code is inactive");
        }
        return voucherRepository.saveAndFlush(GlVoucher.createWithRule(auxiliar.getCode(), NATIVE_RULE_VERSION, headerConcept,
                "NATIVE_OPERATION", operationType, sourceEntityType, sourceEntityId, null));
    }

    private record NativeRouteRule(String auxiliarCode, String sourceEntityType) {
    }

    public GlVoucher createReversal(GlVoucher original, String auxiliarCode, String headerConcept, String operationType) {
        if (original == null || StringUtils.isBlank(auxiliarCode) || StringUtils.isBlank(headerConcept)) {
            throw new IllegalArgumentException("A reversal requires original voucher, Auxiliar and concept");
        }
        GlAuxiliar auxiliar = auxiliarRepository.findById(auxiliarCode.trim())
                .orElseThrow(() -> new IllegalArgumentException("Unknown reversal Auxiliar"));
        if (!auxiliar.isActive()) {
            throw new IllegalArgumentException("Inactive reversal Auxiliar");
        }
        return voucherRepository
                .saveAndFlush(GlVoucher.create(auxiliar.getCode(), headerConcept, "REVERSAL", operationType, null, null, original));
    }
}
