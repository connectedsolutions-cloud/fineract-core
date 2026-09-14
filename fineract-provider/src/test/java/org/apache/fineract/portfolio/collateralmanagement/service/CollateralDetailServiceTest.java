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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.gson.JsonParser;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.fineract.infrastructure.codes.domain.CodeValueRepositoryWrapper;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.ApplicationCurrency;
import org.apache.fineract.organisation.monetary.domain.ApplicationCurrencyRepository;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.AssetRequest;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.PropertyRequest;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.ValuationRequest;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralAsset;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralAssetRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagement;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagementRepositoryWrapper;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralProperty;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralPropertyRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralVehicleRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralManagementDomain;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralRegistrationRepository;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuation;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuationRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagementRepository;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class CollateralDetailServiceTest {

    private ClientCollateralManagementRepositoryWrapper clientCollateralRepository;
    private ClientCollateralAssetRepository assetRepository;
    private ClientCollateralVehicleRepository vehicleRepository;
    private ClientCollateralPropertyRepository propertyRepository;
    private CollateralValuationRepository valuationRepository;
    private ApplicationCurrencyRepository currencyRepository;
    private CollateralDetailService service;
    private ClientCollateralManagement clientCollateral;
    private ClientCollateralAsset asset;

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "test", "Test", "UTC", null));
        PlatformSecurityContext context = mock(PlatformSecurityContext.class);
        AppUser user = mock(AppUser.class);
        when(context.authenticatedUser()).thenReturn(user);
        when(user.getId()).thenReturn(7L);
        clientCollateralRepository = mock(ClientCollateralManagementRepositoryWrapper.class);
        assetRepository = mock(ClientCollateralAssetRepository.class);
        vehicleRepository = mock(ClientCollateralVehicleRepository.class);
        propertyRepository = mock(ClientCollateralPropertyRepository.class);
        valuationRepository = mock(CollateralValuationRepository.class);
        currencyRepository = mock(ApplicationCurrencyRepository.class);
        service = new CollateralDetailService(context, clientCollateralRepository, assetRepository, vehicleRepository, propertyRepository,
                valuationRepository, mock(CollateralRegistrationRepository.class), mock(LoanCollateralManagementRepository.class),
                currencyRepository, mock(CodeValueRepositoryWrapper.class));

        Client client = mock(Client.class);
        when(client.getId()).thenReturn(3L);
        clientCollateral = mock(ClientCollateralManagement.class);
        when(clientCollateral.getId()).thenReturn(10L);
        when(clientCollateral.getClient()).thenReturn(client);
        when(clientCollateralRepository.getCollateral(10L)).thenReturn(clientCollateral);
        asset = new ClientCollateralAsset(clientCollateral, 7L, null);
        asset.setId(50L);
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void storesPropertyDetailsAsTheSingleAssetSubtype() {
        AtomicReference<ClientCollateralProperty> savedProperty = new AtomicReference<>();
        when(assetRepository.findByClientCollateralId(10L)).thenReturn(Optional.empty());
        when(assetRepository.saveAndFlush(any())).thenAnswer(invocation -> {
            ClientCollateralAsset saved = invocation.getArgument(0);
            saved.setId(50L);
            return saved;
        });
        when(propertyRepository.save(any())).thenAnswer(invocation -> {
            savedProperty.set(invocation.getArgument(0));
            return invocation.getArgument(0);
        });
        when(propertyRepository.findById(50L)).thenAnswer(invocation -> Optional.ofNullable(savedProperty.get()));

        PropertyRequest property = new PropertyRequest(null, "Urban lot", "San Salvador", "06", "14", "M-123", "URBAN",
                new BigDecimal("163.44"), "SQUARE_METERS", "FULL_TITLE", false, false, "VALID");
        var result = service.upsertAsset(3L, 10L,
                new AssetRequest("arissto-1", "property", "House and land", true, null, null, null, property));

        assertEquals("PROPERTY", result.assetType());
        assertEquals(new BigDecimal("163.44"), result.property().area());
        assertNull(result.vehicle());
    }

    @Test
    void supersedingFinalValuationKeepsTheOldRecordAndLinksTheReplacement() {
        when(assetRepository.findByClientCollateralId(10L)).thenReturn(Optional.of(asset));
        CollateralValuation previous = valuation("FINAL", new BigDecimal("7000"));
        previous.setId(91L);
        when(valuationRepository.findById(91L)).thenReturn(Optional.of(previous));
        when(currencyRepository.findOneByCode("USD")).thenReturn(mock(ApplicationCurrency.class));
        when(valuationRepository.saveAndFlush(any())).thenAnswer(invocation -> {
            CollateralValuation saved = invocation.getArgument(0);
            saved.setId(92L);
            return saved;
        });

        var result = service.supersedeValuation(3L, 10L, 91L, request(new BigDecimal("8500"), "DRAFT", "INITIAL"));

        assertEquals("SUPERSEDED", previous.getStatus());
        assertEquals("FINAL", result.status());
        assertEquals("REAPPRAISAL", result.valuationType());
        assertEquals(91L, result.supersedesValuationId());
    }

    @Test
    void finalValuationCannotBeEditedInPlace() {
        when(assetRepository.findByClientCollateralId(10L)).thenReturn(Optional.of(asset));
        CollateralValuation previous = valuation("FINAL", new BigDecimal("7000"));
        previous.setId(91L);
        when(valuationRepository.findById(91L)).thenReturn(Optional.of(previous));

        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.updateDraftValuation(3L, 10L, 91L, request(new BigDecimal("8000"), "FINAL", "REAPPRAISAL")));
    }

    @Test
    void loanPledgeFreezesSelectedValuationAndEligibleValue() {
        ClientCollateralManagement collateral = mock(ClientCollateralManagement.class);
        CollateralManagementDomain product = mock(CollateralManagementDomain.class);
        when(collateral.getId()).thenReturn(10L);
        when(collateral.getQuantity()).thenReturn(BigDecimal.ONE);
        when(collateral.getCollaterals()).thenReturn(product);
        when(product.getPctToBase()).thenReturn(new BigDecimal("60"));
        when(clientCollateralRepository.getCollateral(10L)).thenReturn(collateral);
        CollateralValuation valuation = valuation("FINAL", new BigDecimal("10000"));
        valuation.setValuationDate(LocalDate.of(2026, 9, 1));
        CollateralDetailService valuationLookup = mock(CollateralDetailService.class);
        when(valuationLookup.requireFinalValuation(10L, 91L)).thenReturn(valuation);

        LoanCollateralAssembler assembler = new LoanCollateralAssembler(new FromJsonHelper(), mock(CodeValueRepositoryWrapper.class),
                mock(LoanCollateralManagementRepository.class), clientCollateralRepository, valuationLookup);
        var pledge = assembler
                .fromParsedJson(JsonParser
                        .parseString("{\"locale\":\"en\",\"collateral\":[{\"clientCollateralId\":10,\"quantity\":1,\"valuationId\":91}]}"))
                .iterator().next();

        assertEquals(91L, pledge.getValuationId());
        assertEquals(new BigDecimal("10000"), pledge.getPledgedValue());
        assertEquals(new BigDecimal("6000"), pledge.getEligibleValue());
        assertEquals(LocalDate.of(2026, 9, 1), pledge.getValuationDate());
    }

    private CollateralValuation valuation(String status, BigDecimal value) {
        CollateralValuation valuation = new CollateralValuation(asset, 7L, null);
        valuation.setStatus(status);
        valuation.setTotalValue(value);
        valuation.setCurrencyCode("USD");
        valuation.setValuationDate(LocalDate.of(2026, 9, 14));
        valuation.setValuationType("INITIAL");
        return valuation;
    }

    private static ValuationRequest request(BigDecimal value, String status, String type) {
        return new ValuationRequest(null, type, LocalDate.of(2026, 9, 14), "usd", value, null, null, null, null, null, null, null, null,
                status);
    }
}
