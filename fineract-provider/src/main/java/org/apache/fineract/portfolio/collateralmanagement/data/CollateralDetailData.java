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
package org.apache.fineract.portfolio.collateralmanagement.data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

public final class CollateralDetailData {

    private CollateralDetailData() {}

    public record AssetRequest(String externalId, String assetType, String description, Boolean ownedByClient, String ownerRelationship,
            String status, VehicleRequest vehicle, PropertyRequest property) {
    }

    public record VehicleRequest(Integer manufactureYear, String make, String model, String plate, String color, String engineNumber,
            String chassisNumber, String vin, Long vehicleTypeCodeValueId, String vehicleClass, String capacity,
            LocalDate registrationExpiryDate, Long qualityCodeValueId) {
    }

    public record PropertyRequest(Long propertyTypeCodeValueId, String propertyDescription, String address, String departmentCode,
            String municipalityCode, String registryNumber, String propertyNature, BigDecimal area, String areaUnit, String ownershipRights,
            Boolean hasLiens, Boolean hasJudicialAttachment, String municipalClearanceStatus) {
    }

    public record AssetResponse(Long id, Long clientCollateralId, String externalId, String assetType, String description,
            Boolean ownedByClient, String ownerRelationship, String status, VehicleRequest vehicle, PropertyRequest property,
            Long createdById, LocalDateTime createdDate, Long lastModifiedById, LocalDateTime lastModifiedDate) {
    }

    public record ValuationRequest(String externalId, String valuationType, LocalDate valuationDate, String currencyCode,
            BigDecimal totalValue, BigDecimal landValue, BigDecimal constructionValue, BigDecimal marketValue, BigDecimal saleValue,
            String appraiser, String appraisalCompany, String appraiserOpinion, BigDecimal appraisalCost, String status) {
    }

    public record ValuationResponse(Long id, Long assetId, String externalId, String valuationType, LocalDate valuationDate,
            String currencyCode, BigDecimal totalValue, BigDecimal landValue, BigDecimal constructionValue, BigDecimal marketValue,
            BigDecimal saleValue, String appraiser, String appraisalCompany, String appraiserOpinion, BigDecimal appraisalCost,
            String status, Long supersedesValuationId, Long createdById, LocalDateTime createdDate) {
    }

    public record RegistrationRequest(String externalId, Long loanCollateralId, Long responsibleStaffId, LocalDate presentationDate,
            LocalDate registrationDate, String registrationNumber, String status, BigDecimal loanAmount, BigDecimal purchaseAmount,
            String contractType, String notes) {
    }

    public record RegistrationResponse(Long id, Long assetId, String externalId, Long loanCollateralId, Long responsibleStaffId,
            LocalDate presentationDate, LocalDate registrationDate, String registrationNumber, String status, BigDecimal loanAmount,
            BigDecimal purchaseAmount, String contractType, String notes, Long createdById, LocalDateTime createdDate,
            Long lastModifiedById, LocalDateTime lastModifiedDate) {
    }
}
