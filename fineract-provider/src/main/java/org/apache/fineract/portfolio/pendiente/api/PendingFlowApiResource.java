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
package org.apache.fineract.portfolio.pendiente.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.UriInfo;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.serialization.DefaultToApiJsonSerializer;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowData;
import org.apache.fineract.portfolio.pendiente.service.PendingFlowReadPlatformService;
import org.apache.fineract.portfolio.pendiente.service.PendingFlowWritePlatformService;
import org.springframework.stereotype.Component;

@Path("/v1/pending-flows")
@Component
@RequiredArgsConstructor
public class PendingFlowApiResource {

    private final PlatformSecurityContext context;
    private final PendingFlowReadPlatformService readService;
    private final PendingFlowWritePlatformService writeService;
    private final DefaultToApiJsonSerializer<PendingFlowData> toApiJsonSerializer;
    private final FromJsonHelper fromJsonHelper;

    @GET
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveAll(@Context UriInfo uriInfo, @QueryParam("blueprintId") Long blueprintId,
            @QueryParam("creatorId") Long creatorId, @QueryParam("status") String status) {
        context.authenticatedUser().validateHasPermissionTo("view_pendientes");
        List<PendingFlowData> data = readService.retrieveAll(blueprintId, creatorId, status);
        return toApiJsonSerializer.serialize(data);
    }

    @GET
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveOne(@PathParam("id") Long id, @Context UriInfo uriInfo,
            @QueryParam("includeSteps") Boolean includeSteps) {
        context.authenticatedUser().validateHasPermissionTo("view_pendientes");
        boolean include = Boolean.TRUE.equals(includeSteps);
        PendingFlowData data = readService.retrieveOne(id, include);
        return toApiJsonSerializer.serialize(data);
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String create(@Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasPermissionTo("start_pending_flow");
        Long blueprintId = readBlueprintIdFromJson(apiRequestBodyAsJson);
        validateResponsableUserId(apiRequestBodyAsJson);
        PendingFlowData data = writeService.createFlowAndFirstStep(blueprintId, apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }

    private Long readBlueprintIdFromJson(String json) {
        if (json == null || json.isBlank()) {
            throw new IllegalArgumentException("blueprintId is required");
        }
        var element = fromJsonHelper.parse(json);
        if (element == null || !element.isJsonObject()) {
            throw new IllegalArgumentException("blueprintId is required");
        }
        var object = element.getAsJsonObject();
        if (!object.has("blueprintId")) {
            throw new IllegalArgumentException("blueprintId is required");
        }
        return fromJsonHelper.extractLongNamed("blueprintId", object);
    }

    private void validateResponsableUserId(String json) {
        var element = fromJsonHelper.parse(json);
        if (element == null || !element.isJsonObject()) {
            throw new IllegalArgumentException("responsableUserId is required");
        }
        var object = element.getAsJsonObject();
        if (!object.has("responsableUserId") || object.get("responsableUserId").isJsonNull()) {
            throw new IllegalArgumentException("responsableUserId is required");
        }
    }
}
