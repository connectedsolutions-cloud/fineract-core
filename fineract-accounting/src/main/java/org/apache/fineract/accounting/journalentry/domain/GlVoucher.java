/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor
 * license agreements. See the NOTICE file distributed with this work for
 * additional information regarding copyright ownership. The ASF licenses this
 * file to you under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain a
 * copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.accounting.journalentry.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.LocalDateTime;
import lombok.Getter;
import org.apache.commons.lang3.StringUtils;

/** Metadata for one posted journal group. Accounting amounts remain on {@link JournalEntry}. */
@Entity
@Getter
@Table(name = "credesal_gl_voucher")
public class GlVoucher {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "auxiliar_code", length = 32)
    private String auxiliarCode;

    @Column(name = "auxiliar_rule_version", length = 32)
    private String auxiliarRuleVersion;

    @Column(name = "header_concept", columnDefinition = "text")
    private String headerConcept;

    @Column(name = "posting_category", length = 32, nullable = false)
    private String postingCategory = "REGULAR";

    @Column(name = "origin", length = 40, nullable = false)
    private String origin;

    @Column(name = "operation_type", length = 80, nullable = false)
    private String operationType;

    @Column(name = "source_entity_type", length = 80)
    private String sourceEntityType;

    @Column(name = "source_entity_id", length = 80)
    private String sourceEntityId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "reverses_voucher_id")
    private GlVoucher reversesVoucher;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;

    protected GlVoucher() {}

    public static GlVoucher create(String auxiliarCode, String headerConcept, String origin, String operationType, String sourceEntityType,
            String sourceEntityId, GlVoucher reversesVoucher) {
        if (StringUtils.isBlank(origin) || StringUtils.isBlank(operationType)) {
            throw new IllegalArgumentException("Voucher origin and operation type are required");
        }
        GlVoucher voucher = new GlVoucher();
        voucher.auxiliarCode = StringUtils.trimToNull(auxiliarCode);
        voucher.headerConcept = StringUtils.trimToNull(headerConcept);
        voucher.origin = origin;
        voucher.operationType = operationType;
        voucher.sourceEntityType = StringUtils.trimToNull(sourceEntityType);
        voucher.sourceEntityId = StringUtils.trimToNull(sourceEntityId);
        voucher.reversesVoucher = reversesVoucher;
        return voucher;
    }

    public static GlVoucher createWithRule(String auxiliarCode, String auxiliarRuleVersion, String headerConcept, String origin,
            String operationType, String sourceEntityType, String sourceEntityId, GlVoucher reversesVoucher) {
        GlVoucher voucher = create(auxiliarCode, headerConcept, origin, operationType, sourceEntityType, sourceEntityId, reversesVoucher);
        voucher.auxiliarRuleVersion = StringUtils.trimToNull(auxiliarRuleVersion);
        return voucher;
    }

    public void markAnnualClosing() {
        this.postingCategory = "CLOSING";
    }
}
