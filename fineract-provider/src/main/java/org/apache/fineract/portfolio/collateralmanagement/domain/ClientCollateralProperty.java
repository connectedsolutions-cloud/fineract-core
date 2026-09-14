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
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.MapsId;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "m_client_collateral_property")
@Getter
@Setter
@NoArgsConstructor
public class ClientCollateralProperty {

    @Id
    @Column(name = "asset_id")
    private Long assetId;
    @MapsId
    @OneToOne(optional = false)
    @JoinColumn(name = "asset_id")
    private ClientCollateralAsset asset;
    @Column(name = "property_type_cv_id")
    private Long propertyTypeCodeValueId;
    @Column(name = "property_description", length = 1000)
    private String propertyDescription;
    @Column(name = "address", length = 500)
    private String address;
    @Column(name = "department_code", length = 20)
    private String departmentCode;
    @Column(name = "municipality_code", length = 20)
    private String municipalityCode;
    @Column(name = "registry_number", length = 100)
    private String registryNumber;
    @Column(name = "property_nature", length = 50)
    private String propertyNature;
    @Column(name = "area", precision = 19, scale = 6)
    private BigDecimal area;
    @Column(name = "area_unit", length = 30)
    private String areaUnit;
    @Column(name = "ownership_rights", length = 500)
    private String ownershipRights;
    @Column(name = "has_liens")
    private Boolean hasLiens;
    @Column(name = "has_judicial_attachment")
    private Boolean hasJudicialAttachment;
    @Column(name = "municipal_clearance_status", length = 50)
    private String municipalClearanceStatus;

    public ClientCollateralProperty(ClientCollateralAsset asset) {
        this.asset = asset;
    }
}
