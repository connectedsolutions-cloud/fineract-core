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
package org.apache.fineract.portfolio.shareaccounts.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "credesal_share_certificate_beneficiary")
@Getter
@Setter
@NoArgsConstructor
public class ShareCertificateBeneficiary extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false, fetch = FetchType.LAZY)
    @JoinColumn(name = "certificate_id", nullable = false)
    private ShareCertificate certificate;

    @Column(name = "source_system", length = 32, nullable = false)
    private String sourceSystem;

    @Column(name = "source_key", length = 500, nullable = false)
    private String sourceKey;

    @Column(name = "source_hash", length = 64, nullable = false)
    private String sourceHash;

    @Column(name = "first_names", length = 50)
    private String firstNames;

    @Column(name = "last_names", length = 50)
    private String lastNames;

    @Column(name = "relationship", length = 50)
    private String relationship;

    @Column(name = "percentage", scale = 2, precision = 5)
    private BigDecimal percentage;

    @Column(name = "address", length = 254)
    private String address;

    @Column(name = "phone", length = 15)
    private String phone;

    @Column(name = "date_of_birth")
    private LocalDate dateOfBirth;

    @Column(name = "notify_designation")
    private Boolean notifyDesignation;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
}
