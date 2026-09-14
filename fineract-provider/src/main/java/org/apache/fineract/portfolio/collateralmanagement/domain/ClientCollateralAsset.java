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
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_client_collateral_asset")
@Getter
@Setter
@NoArgsConstructor
public class ClientCollateralAsset extends AbstractPersistableCustom<Long> {

    @OneToOne(optional = false)
    @JoinColumn(name = "client_collateral_id", nullable = false, unique = true)
    private ClientCollateralManagement clientCollateral;

    @Column(name = "external_id", length = 100, unique = true)
    private String externalId;
    @Column(name = "asset_type", nullable = false, length = 20)
    private String assetType;
    @Column(name = "description", length = 500)
    private String description;
    @Column(name = "owned_by_client")
    private Boolean ownedByClient;
    @Column(name = "owner_relationship", length = 100)
    private String ownerRelationship;
    @Column(name = "status", nullable = false, length = 20)
    private String status;
    @Column(name = "createdby_id")
    private Long createdById;
    @Column(name = "created_date")
    private LocalDateTime createdDate;
    @Column(name = "lastmodifiedby_id")
    private Long lastModifiedById;
    @Column(name = "lastmodified_date")
    private LocalDateTime lastModifiedDate;

    public ClientCollateralAsset(ClientCollateralManagement clientCollateral, Long userId, LocalDateTime now) {
        this.clientCollateral = clientCollateral;
        this.createdById = userId;
        this.createdDate = now;
        this.status = "ACTIVE";
    }
}
