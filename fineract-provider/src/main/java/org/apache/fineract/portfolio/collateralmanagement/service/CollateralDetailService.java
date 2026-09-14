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
package org.apache.fineract.portfolio.collateralmanagement.service;

import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.AssetRequest;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.AssetResponse;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.PropertyRequest;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.RegistrationRequest;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.RegistrationResponse;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.ValuationRequest;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.ValuationResponse;
import static org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.VehicleRequest;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.codes.domain.CodeValueRepositoryWrapper;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.ApplicationCurrencyRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralAsset;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralAssetRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagement;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagementRepositoryWrapper;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralProperty;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralPropertyRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralVehicle;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralVehicleRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralRegistration;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralRegistrationRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuation;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuationRepository;
import org.apache.fineract.portfolio.collateralmanagement.exception.CollateralDetailNotFoundException;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagement;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagementRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class CollateralDetailService {

    private static final Set<String> ASSET_TYPES = Set.of("VEHICLE", "PROPERTY", "OTHER");
    private static final Set<String> ASSET_STATUSES = Set.of("ACTIVE", "INACTIVE");
    private static final Set<String> VALUATION_TYPES = Set.of("INITIAL", "REAPPRAISAL");
    private static final Set<String> VALUATION_STATUSES = Set.of("DRAFT", "FINAL");

    private final PlatformSecurityContext context;
    private final ClientCollateralManagementRepositoryWrapper clientCollateralRepository;
    private final ClientCollateralAssetRepository assetRepository;
    private final ClientCollateralVehicleRepository vehicleRepository;
    private final ClientCollateralPropertyRepository propertyRepository;
    private final CollateralValuationRepository valuationRepository;
    private final CollateralRegistrationRepository registrationRepository;
    private final LoanCollateralManagementRepository loanCollateralRepository;
    private final ApplicationCurrencyRepository currencyRepository;
    private final CodeValueRepositoryWrapper codeValueRepository;

    @Transactional(readOnly = true)
    public AssetResponse getAsset(Long clientId, Long clientCollateralId) {
        return toResponse(requireAsset(clientId, clientCollateralId));
    }

    @Transactional
    public AssetResponse upsertAsset(Long clientId, Long clientCollateralId, AssetRequest request) {
        if (request == null) {
            throw rule("asset.required", "asset is required");
        }
        ClientCollateralManagement clientCollateral = requireClientCollateral(clientId, clientCollateralId);
        Long userId = context.authenticatedUser().getId();
        LocalDateTime now = DateUtils.getLocalDateTimeOfTenant();
        ClientCollateralAsset asset = assetRepository.findByClientCollateralId(clientCollateralId)
                .orElseGet(() -> new ClientCollateralAsset(clientCollateral, userId, now));
        String assetType = normalized(request.assetType(), "assetType");
        requireOneOf(assetType, ASSET_TYPES, "assetType");
        String status = StringUtils.isBlank(request.status()) ? "ACTIVE" : normalized(request.status(), "status");
        requireOneOf(status, ASSET_STATUSES, "status");
        asset.setExternalId(blankToNull(request.externalId()));
        asset.setAssetType(assetType);
        asset.setDescription(blankToNull(request.description()));
        asset.setOwnedByClient(request.ownedByClient());
        asset.setOwnerRelationship(blankToNull(request.ownerRelationship()));
        asset.setStatus(status);
        asset.setLastModifiedById(userId);
        asset.setLastModifiedDate(now);
        asset = assetRepository.saveAndFlush(asset);
        final ClientCollateralAsset savedAsset = asset;

        if ("VEHICLE".equals(assetType)) {
            if (request.vehicle() == null) {
                throw rule("vehicle.required", "vehicle details are required when assetType is VEHICLE");
            }
            propertyRepository.findById(savedAsset.getId()).ifPresent(propertyRepository::delete);
            ClientCollateralVehicle vehicle = vehicleRepository.findById(savedAsset.getId())
                    .orElseGet(() -> new ClientCollateralVehicle(savedAsset));
            applyVehicle(vehicle, request.vehicle());
            vehicleRepository.save(vehicle);
        } else if ("PROPERTY".equals(assetType)) {
            if (request.property() == null) {
                throw rule("property.required", "property details are required when assetType is PROPERTY");
            }
            vehicleRepository.findById(savedAsset.getId()).ifPresent(vehicleRepository::delete);
            ClientCollateralProperty property = propertyRepository.findById(savedAsset.getId())
                    .orElseGet(() -> new ClientCollateralProperty(savedAsset));
            applyProperty(property, request.property());
            propertyRepository.save(property);
        } else {
            vehicleRepository.findById(savedAsset.getId()).ifPresent(vehicleRepository::delete);
            propertyRepository.findById(savedAsset.getId()).ifPresent(propertyRepository::delete);
        }
        return toResponse(asset);
    }

    @Transactional(readOnly = true)
    public List<ValuationResponse> getValuations(Long clientId, Long clientCollateralId) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        return valuationRepository.findByAssetIdOrderByValuationDateDescIdDesc(asset.getId()).stream().map(this::toResponse).toList();
    }

    @Transactional(readOnly = true)
    public ValuationResponse getValuation(Long clientId, Long clientCollateralId, Long valuationId) {
        return toResponse(requireValuation(requireAsset(clientId, clientCollateralId), valuationId));
    }

    @Transactional
    public ValuationResponse createValuation(Long clientId, Long clientCollateralId, ValuationRequest request) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralValuation valuation = new CollateralValuation(asset, context.authenticatedUser().getId(),
                DateUtils.getLocalDateTimeOfTenant());
        applyValuation(valuation, request);
        return toResponse(valuationRepository.saveAndFlush(valuation));
    }

    @Transactional
    public ValuationResponse updateDraftValuation(Long clientId, Long clientCollateralId, Long valuationId, ValuationRequest request) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralValuation valuation = requireValuation(asset, valuationId);
        if (!"DRAFT".equals(valuation.getStatus())) {
            throw rule("valuation.final.immutable", "A final or superseded valuation cannot be edited");
        }
        applyValuation(valuation, request);
        valuation.setLastModifiedById(context.authenticatedUser().getId());
        valuation.setLastModifiedDate(DateUtils.getLocalDateTimeOfTenant());
        return toResponse(valuationRepository.saveAndFlush(valuation));
    }

    @Transactional
    public ValuationResponse supersedeValuation(Long clientId, Long clientCollateralId, Long valuationId, ValuationRequest replacement) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralValuation previous = requireValuation(asset, valuationId);
        if (!"FINAL".equals(previous.getStatus())) {
            throw rule("valuation.not.final", "Only a final valuation can be superseded");
        }
        previous.setStatus("SUPERSEDED");
        previous.setLastModifiedById(context.authenticatedUser().getId());
        previous.setLastModifiedDate(DateUtils.getLocalDateTimeOfTenant());
        valuationRepository.save(previous);
        CollateralValuation next = new CollateralValuation(asset, context.authenticatedUser().getId(),
                DateUtils.getLocalDateTimeOfTenant());
        applyValuation(next, replacement);
        next.setValuationType("REAPPRAISAL");
        next.setStatus("FINAL");
        next.setSupersedesValuationId(previous.getId());
        return toResponse(valuationRepository.saveAndFlush(next));
    }

    @Transactional(readOnly = true)
    public List<RegistrationResponse> getRegistrations(Long clientId, Long clientCollateralId) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        return registrationRepository.findByAssetIdOrderByIdDesc(asset.getId()).stream().map(this::toResponse).toList();
    }

    @Transactional(readOnly = true)
    public RegistrationResponse getRegistration(Long clientId, Long clientCollateralId, Long registrationId) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralRegistration registration = registrationRepository.findById(registrationId)
                .filter(item -> item.getAsset().getId().equals(asset.getId()))
                .orElseThrow(() -> new CollateralDetailNotFoundException("registration", registrationId));
        return toResponse(registration);
    }

    @Transactional
    public RegistrationResponse createRegistration(Long clientId, Long clientCollateralId, RegistrationRequest request) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralRegistration registration = new CollateralRegistration(asset, context.authenticatedUser().getId(),
                DateUtils.getLocalDateTimeOfTenant());
        applyRegistration(registration, request, clientCollateralId);
        return toResponse(registrationRepository.saveAndFlush(registration));
    }

    @Transactional
    public RegistrationResponse updateRegistration(Long clientId, Long clientCollateralId, Long registrationId,
            RegistrationRequest request) {
        ClientCollateralAsset asset = requireAsset(clientId, clientCollateralId);
        CollateralRegistration registration = registrationRepository.findById(registrationId)
                .filter(item -> item.getAsset().getId().equals(asset.getId()))
                .orElseThrow(() -> new CollateralDetailNotFoundException("registration", registrationId));
        applyRegistration(registration, request, clientCollateralId);
        registration.setLastModifiedById(context.authenticatedUser().getId());
        registration.setLastModifiedDate(DateUtils.getLocalDateTimeOfTenant());
        return toResponse(registrationRepository.saveAndFlush(registration));
    }

    @Transactional(readOnly = true)
    public CollateralValuation requireFinalValuation(Long clientCollateralId, Long valuationId) {
        ClientCollateralAsset asset = assetRepository.findByClientCollateralId(clientCollateralId)
                .orElseThrow(() -> new CollateralDetailNotFoundException("asset", clientCollateralId));
        CollateralValuation valuation = requireValuation(asset, valuationId);
        if (!"FINAL".equals(valuation.getStatus())) {
            throw rule("valuation.not.final", "The selected valuation must be final");
        }
        return valuation;
    }

    private ClientCollateralManagement requireClientCollateral(Long clientId, Long clientCollateralId) {
        ClientCollateralManagement collateral = clientCollateralRepository.getCollateral(clientCollateralId);
        if (!collateral.getClient().getId().equals(clientId)) {
            throw rule("client.mismatch", "The collateral does not belong to the requested client");
        }
        return collateral;
    }

    private ClientCollateralAsset requireAsset(Long clientId, Long clientCollateralId) {
        requireClientCollateral(clientId, clientCollateralId);
        return assetRepository.findByClientCollateralId(clientCollateralId)
                .orElseThrow(() -> new CollateralDetailNotFoundException("asset", clientCollateralId));
    }

    private CollateralValuation requireValuation(ClientCollateralAsset asset, Long valuationId) {
        return valuationRepository.findById(valuationId).filter(item -> item.getAsset().getId().equals(asset.getId()))
                .orElseThrow(() -> new CollateralDetailNotFoundException("valuation", valuationId));
    }

    private void applyValuation(CollateralValuation valuation, ValuationRequest request) {
        if (request == null || request.valuationDate() == null || request.totalValue() == null || request.totalValue().signum() <= 0) {
            throw rule("valuation.invalid", "valuationDate and a positive totalValue are required");
        }
        String type = normalized(request.valuationType(), "valuationType");
        requireOneOf(type, VALUATION_TYPES, "valuationType");
        String status = StringUtils.isBlank(request.status()) ? "DRAFT" : normalized(request.status(), "status");
        requireOneOf(status, VALUATION_STATUSES, "status");
        String currency = normalized(request.currencyCode(), "currencyCode");
        if (currencyRepository.findOneByCode(currency) == null) {
            throw rule("currency.invalid", "The valuation currency is not configured");
        }
        requireNonNegative(request.landValue(), "landValue");
        requireNonNegative(request.constructionValue(), "constructionValue");
        requireNonNegative(request.marketValue(), "marketValue");
        requireNonNegative(request.saleValue(), "saleValue");
        requireNonNegative(request.appraisalCost(), "appraisalCost");
        valuation.setExternalId(blankToNull(request.externalId()));
        valuation.setValuationType(type);
        valuation.setValuationDate(request.valuationDate());
        valuation.setCurrencyCode(currency);
        valuation.setTotalValue(request.totalValue());
        valuation.setLandValue(request.landValue());
        valuation.setConstructionValue(request.constructionValue());
        valuation.setMarketValue(request.marketValue());
        valuation.setSaleValue(request.saleValue());
        valuation.setAppraiser(blankToNull(request.appraiser()));
        valuation.setAppraisalCompany(blankToNull(request.appraisalCompany()));
        valuation.setAppraiserOpinion(blankToNull(request.appraiserOpinion()));
        valuation.setAppraisalCost(request.appraisalCost());
        valuation.setStatus(status);
    }

    private void applyRegistration(CollateralRegistration registration, RegistrationRequest request, Long clientCollateralId) {
        if (request == null) {
            throw rule("registration.required", "registration is required");
        }
        if (request.loanCollateralId() != null) {
            LoanCollateralManagement loanCollateral = loanCollateralRepository.findById(request.loanCollateralId())
                    .orElseThrow(() -> new CollateralDetailNotFoundException("loan-collateral", request.loanCollateralId()));
            if (!loanCollateral.getClientCollateralManagement().getId().equals(clientCollateralId)) {
                throw rule("registration.loan.collateral.mismatch", "The loan collateral does not pledge this asset");
            }
        }
        requireNonNegative(request.loanAmount(), "loanAmount");
        requireNonNegative(request.purchaseAmount(), "purchaseAmount");
        registration.setExternalId(blankToNull(request.externalId()));
        registration.setLoanCollateralId(request.loanCollateralId());
        registration.setResponsibleStaffId(request.responsibleStaffId());
        registration.setPresentationDate(request.presentationDate());
        registration.setRegistrationDate(request.registrationDate());
        registration.setRegistrationNumber(blankToNull(request.registrationNumber()));
        registration.setStatus(blankToNull(request.status()));
        registration.setLoanAmount(request.loanAmount());
        registration.setPurchaseAmount(request.purchaseAmount());
        registration.setContractType(blankToNull(request.contractType()));
        registration.setNotes(blankToNull(request.notes()));
    }

    private void applyVehicle(ClientCollateralVehicle vehicle, VehicleRequest request) {
        if (request.manufactureYear() != null && (request.manufactureYear() < 1886 || request.manufactureYear() > 2200)) {
            throw rule("vehicle.year.invalid", "manufactureYear is outside the accepted range");
        }
        if (request.vehicleTypeCodeValueId() != null) {
            codeValueRepository.findOneByCodeNameAndIdWithNotFoundDetection("Collateral vehicle type", request.vehicleTypeCodeValueId());
        }
        if (request.qualityCodeValueId() != null) {
            codeValueRepository.findOneByCodeNameAndIdWithNotFoundDetection("Collateral asset quality", request.qualityCodeValueId());
        }
        vehicle.setManufactureYear(request.manufactureYear());
        vehicle.setMake(blankToNull(request.make()));
        vehicle.setModel(blankToNull(request.model()));
        vehicle.setPlate(blankToNull(request.plate()));
        vehicle.setColor(blankToNull(request.color()));
        vehicle.setEngineNumber(blankToNull(request.engineNumber()));
        vehicle.setChassisNumber(blankToNull(request.chassisNumber()));
        vehicle.setVin(blankToNull(request.vin()));
        vehicle.setVehicleTypeCodeValueId(request.vehicleTypeCodeValueId());
        vehicle.setVehicleClass(blankToNull(request.vehicleClass()));
        vehicle.setCapacity(blankToNull(request.capacity()));
        vehicle.setRegistrationExpiryDate(request.registrationExpiryDate());
        vehicle.setQualityCodeValueId(request.qualityCodeValueId());
    }

    private void applyProperty(ClientCollateralProperty property, PropertyRequest request) {
        requireNonNegative(request.area(), "area");
        if (request.propertyTypeCodeValueId() != null) {
            codeValueRepository.findOneByCodeNameAndIdWithNotFoundDetection("Collateral property type", request.propertyTypeCodeValueId());
        }
        property.setPropertyTypeCodeValueId(request.propertyTypeCodeValueId());
        property.setPropertyDescription(blankToNull(request.propertyDescription()));
        property.setAddress(blankToNull(request.address()));
        property.setDepartmentCode(blankToNull(request.departmentCode()));
        property.setMunicipalityCode(blankToNull(request.municipalityCode()));
        property.setRegistryNumber(blankToNull(request.registryNumber()));
        property.setPropertyNature(blankToNull(request.propertyNature()));
        property.setArea(request.area());
        property.setAreaUnit(blankToNull(request.areaUnit()));
        property.setOwnershipRights(blankToNull(request.ownershipRights()));
        property.setHasLiens(request.hasLiens());
        property.setHasJudicialAttachment(request.hasJudicialAttachment());
        property.setMunicipalClearanceStatus(blankToNull(request.municipalClearanceStatus()));
    }

    private AssetResponse toResponse(ClientCollateralAsset asset) {
        VehicleRequest vehicle = vehicleRepository.findById(asset.getId())
                .map(item -> new VehicleRequest(item.getManufactureYear(), item.getMake(), item.getModel(), item.getPlate(),
                        item.getColor(), item.getEngineNumber(), item.getChassisNumber(), item.getVin(), item.getVehicleTypeCodeValueId(),
                        item.getVehicleClass(), item.getCapacity(), item.getRegistrationExpiryDate(), item.getQualityCodeValueId()))
                .orElse(null);
        PropertyRequest property = propertyRepository.findById(asset.getId())
                .map(item -> new PropertyRequest(item.getPropertyTypeCodeValueId(), item.getPropertyDescription(), item.getAddress(),
                        item.getDepartmentCode(), item.getMunicipalityCode(), item.getRegistryNumber(), item.getPropertyNature(),
                        item.getArea(), item.getAreaUnit(), item.getOwnershipRights(), item.getHasLiens(), item.getHasJudicialAttachment(),
                        item.getMunicipalClearanceStatus()))
                .orElse(null);
        return new AssetResponse(asset.getId(), asset.getClientCollateral().getId(), asset.getExternalId(), asset.getAssetType(),
                asset.getDescription(), asset.getOwnedByClient(), asset.getOwnerRelationship(), asset.getStatus(), vehicle, property,
                asset.getCreatedById(), asset.getCreatedDate(), asset.getLastModifiedById(), asset.getLastModifiedDate());
    }

    private ValuationResponse toResponse(CollateralValuation item) {
        return new ValuationResponse(item.getId(), item.getAsset().getId(), item.getExternalId(), item.getValuationType(),
                item.getValuationDate(), item.getCurrencyCode(), item.getTotalValue(), item.getLandValue(), item.getConstructionValue(),
                item.getMarketValue(), item.getSaleValue(), item.getAppraiser(), item.getAppraisalCompany(), item.getAppraiserOpinion(),
                item.getAppraisalCost(), item.getStatus(), item.getSupersedesValuationId(), item.getCreatedById(), item.getCreatedDate());
    }

    private RegistrationResponse toResponse(CollateralRegistration item) {
        return new RegistrationResponse(item.getId(), item.getAsset().getId(), item.getExternalId(), item.getLoanCollateralId(),
                item.getResponsibleStaffId(), item.getPresentationDate(), item.getRegistrationDate(), item.getRegistrationNumber(),
                item.getStatus(), item.getLoanAmount(), item.getPurchaseAmount(), item.getContractType(), item.getNotes(),
                item.getCreatedById(), item.getCreatedDate(), item.getLastModifiedById(), item.getLastModifiedDate());
    }

    private static String normalized(String value, String field) {
        if (StringUtils.isBlank(value)) throw rule(field + ".required", field + " is required");
        return value.trim().toUpperCase(Locale.ROOT);
    }

    private static String blankToNull(String value) {
        return StringUtils.trimToNull(value);
    }

    private static void requireOneOf(String value, Set<String> allowed, String field) {
        if (!allowed.contains(value)) throw rule(field + ".invalid", field + " must be one of " + allowed);
    }

    private static void requireNonNegative(BigDecimal value, String field) {
        if (value != null && value.signum() < 0) throw rule(field + ".negative", field + " must not be negative");
    }

    private static GeneralPlatformDomainRuleException rule(String code, String message) {
        return new GeneralPlatformDomainRuleException("error.msg.collateral." + code, message);
    }
}
