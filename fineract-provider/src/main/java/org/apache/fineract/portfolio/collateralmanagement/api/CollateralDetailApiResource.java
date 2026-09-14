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
package org.apache.fineract.portfolio.collateralmanagement.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.AssetRequest;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.AssetResponse;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.RegistrationRequest;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.RegistrationResponse;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.ValuationRequest;
import org.apache.fineract.portfolio.collateralmanagement.data.CollateralDetailData.ValuationResponse;
import org.apache.fineract.portfolio.collateralmanagement.service.CollateralDetailService;
import org.springframework.stereotype.Component;

@Path("/v1/clients/{clientId}/collaterals/{clientCollateralId}")
@Component
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@Tag(name = "Collateral Details", description = "Asset, appraisal, and registration details for client collateral")
@RequiredArgsConstructor
public class CollateralDetailApiResource {

    public static final String READ_PERMISSION = "READ_COLLATERAL_DETAILS";
    public static final String MANAGE_PERMISSION = "MANAGE_COLLATERAL_DETAILS";

    private final PlatformSecurityContext context;
    private final CollateralDetailService service;

    @GET
    @Path("asset")
    @Operation(summary = "Get a client's collateral asset details")
    public AssetResponse getAsset(@PathParam("clientId") Long clientId, @PathParam("clientCollateralId") Long clientCollateralId) {
        validateRead();
        return service.getAsset(clientId, clientCollateralId);
    }

    @PUT
    @Path("asset")
    @Operation(summary = "Create or update a client's collateral asset details")
    public AssetResponse upsertAsset(@PathParam("clientId") Long clientId, @PathParam("clientCollateralId") Long clientCollateralId,
            AssetRequest request) {
        validateManage();
        return service.upsertAsset(clientId, clientCollateralId, request);
    }

    @GET
    @Path("valuations")
    @Operation(summary = "List collateral appraisals")
    public List<ValuationResponse> getValuations(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId) {
        validateRead();
        return service.getValuations(clientId, clientCollateralId);
    }

    @GET
    @Path("valuations/{valuationId}")
    @Operation(summary = "Get a collateral appraisal")
    public ValuationResponse getValuation(@PathParam("clientId") Long clientId, @PathParam("clientCollateralId") Long clientCollateralId,
            @PathParam("valuationId") Long valuationId) {
        validateRead();
        return service.getValuation(clientId, clientCollateralId, valuationId);
    }

    @POST
    @Path("valuations")
    @Operation(summary = "Add a collateral appraisal")
    public ValuationResponse createValuation(@PathParam("clientId") Long clientId, @PathParam("clientCollateralId") Long clientCollateralId,
            ValuationRequest request) {
        validateManage();
        return service.createValuation(clientId, clientCollateralId, request);
    }

    @PUT
    @Path("valuations/{valuationId}")
    @Operation(summary = "Update a draft collateral appraisal")
    public ValuationResponse updateValuation(@PathParam("clientId") Long clientId, @PathParam("clientCollateralId") Long clientCollateralId,
            @PathParam("valuationId") Long valuationId, ValuationRequest request) {
        validateManage();
        return service.updateDraftValuation(clientId, clientCollateralId, valuationId, request);
    }

    @POST
    @Path("valuations/{valuationId}")
    @Operation(summary = "Supersede a final appraisal with a new final appraisal")
    public ValuationResponse commandValuation(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId, @PathParam("valuationId") Long valuationId,
            @QueryParam("command") String command, ValuationRequest replacement) {
        validateManage();
        if (!"supersede".equalsIgnoreCase(command)) {
            throw new GeneralPlatformDomainRuleException("error.msg.collateral.valuation.command.invalid",
                    "The supported valuation command is supersede");
        }
        return service.supersedeValuation(clientId, clientCollateralId, valuationId, replacement);
    }

    @GET
    @Path("registrations")
    @Operation(summary = "List collateral registrations")
    public List<RegistrationResponse> getRegistrations(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId) {
        validateRead();
        return service.getRegistrations(clientId, clientCollateralId);
    }

    @GET
    @Path("registrations/{registrationId}")
    @Operation(summary = "Get a collateral registration")
    public RegistrationResponse getRegistration(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId, @PathParam("registrationId") Long registrationId) {
        validateRead();
        return service.getRegistration(clientId, clientCollateralId, registrationId);
    }

    @POST
    @Path("registrations")
    @Operation(summary = "Add a collateral registration")
    public RegistrationResponse createRegistration(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId, RegistrationRequest request) {
        validateManage();
        return service.createRegistration(clientId, clientCollateralId, request);
    }

    @PUT
    @Path("registrations/{registrationId}")
    @Operation(summary = "Update a collateral registration")
    public RegistrationResponse updateRegistration(@PathParam("clientId") Long clientId,
            @PathParam("clientCollateralId") Long clientCollateralId, @PathParam("registrationId") Long registrationId,
            RegistrationRequest request) {
        validateManage();
        return service.updateRegistration(clientId, clientCollateralId, registrationId, request);
    }

    private void validateRead() {
        context.authenticatedUser().validateHasPermissionTo("read collateral details",
                List.of(READ_PERMISSION, MANAGE_PERMISSION, "ALL_FUNCTIONS_READ"));
    }

    private void validateManage() {
        context.authenticatedUser().validateHasPermissionTo(MANAGE_PERMISSION);
    }
}
