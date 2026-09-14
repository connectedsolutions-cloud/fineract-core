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
package org.apache.fineract.portfolio.collateralmanagement.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
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
@Table(name = "m_collateral_registration")
@Getter
@Setter
@NoArgsConstructor
public class CollateralRegistration extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "asset_id", nullable = false)
    private ClientCollateralAsset asset;
    @Column(name = "loan_collateral_id")
    private Long loanCollateralId;
    @Column(name = "external_id", length = 100, unique = true)
    private String externalId;
    @Column(name = "responsible_staff_id")
    private Long responsibleStaffId;
    @Column(name = "presentation_date")
    private LocalDate presentationDate;
    @Column(name = "registration_date")
    private LocalDate registrationDate;
    @Column(name = "registration_number", length = 100)
    private String registrationNumber;
    @Column(name = "status", length = 50)
    private String status;
    @Column(name = "loan_amount", precision = 19, scale = 6)
    private BigDecimal loanAmount;
    @Column(name = "purchase_amount", precision = 19, scale = 6)
    private BigDecimal purchaseAmount;
    @Column(name = "contract_type", length = 100)
    private String contractType;
    @Column(name = "notes", length = 1000)
    private String notes;
    @Column(name = "createdby_id")
    private Long createdById;
    @Column(name = "created_date")
    private LocalDateTime createdDate;
    @Column(name = "lastmodifiedby_id")
    private Long lastModifiedById;
    @Column(name = "lastmodified_date")
    private LocalDateTime lastModifiedDate;

    public CollateralRegistration(ClientCollateralAsset asset, Long userId, LocalDateTime now) {
        this.asset = asset;
        this.createdById = userId;
        this.createdDate = now;
    }
}
