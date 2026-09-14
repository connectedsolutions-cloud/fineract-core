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
import java.time.LocalDate;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "m_client_collateral_vehicle")
@Getter
@Setter
@NoArgsConstructor
public class ClientCollateralVehicle {

    @Id
    @Column(name = "asset_id")
    private Long assetId;
    @MapsId
    @OneToOne(optional = false)
    @JoinColumn(name = "asset_id")
    private ClientCollateralAsset asset;
    @Column(name = "manufacture_year")
    private Integer manufactureYear;
    @Column(name = "make", length = 100)
    private String make;
    @Column(name = "model", length = 100)
    private String model;
    @Column(name = "plate", length = 50)
    private String plate;
    @Column(name = "color", length = 50)
    private String color;
    @Column(name = "engine_number", length = 100)
    private String engineNumber;
    @Column(name = "chassis_number", length = 100)
    private String chassisNumber;
    @Column(name = "vin", length = 100)
    private String vin;
    @Column(name = "vehicle_type_cv_id")
    private Long vehicleTypeCodeValueId;
    @Column(name = "vehicle_class", length = 100)
    private String vehicleClass;
    @Column(name = "capacity", length = 100)
    private String capacity;
    @Column(name = "registration_expiry_date")
    private LocalDate registrationExpiryDate;
    @Column(name = "quality_cv_id")
    private Long qualityCodeValueId;

    public ClientCollateralVehicle(ClientCollateralAsset asset) {
        this.asset = asset;
    }
}
