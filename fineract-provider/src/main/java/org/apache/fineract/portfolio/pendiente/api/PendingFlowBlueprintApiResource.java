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
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.UriInfo;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.serialization.DefaultToApiJsonSerializer;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowBlueprintData;
import org.apache.fineract.portfolio.pendiente.service.PendingFlowBlueprintReadPlatformService;
import org.apache.fineract.portfolio.pendiente.service.PendingFlowBlueprintWritePlatformService;
import org.springframework.stereotype.Component;

@Path("/v1/pending-flow-blueprints")
@Component
@RequiredArgsConstructor
public class PendingFlowBlueprintApiResource {

    private final PlatformSecurityContext context;
    private final PendingFlowBlueprintReadPlatformService readService;
    private final PendingFlowBlueprintWritePlatformService writeService;
    private final DefaultToApiJsonSerializer<PendingFlowBlueprintData> toApiJsonSerializer;

    @GET
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveAll(@Context UriInfo uriInfo) {
        context.authenticatedUser().validateHasReadPermission("view_pendientes");
        List<PendingFlowBlueprintData> data = readService.retrieveAll();
        return toApiJsonSerializer.serialize(data);
    }

    @GET
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveOne(@PathParam("id") Long id, @Context UriInfo uriInfo) {
        context.authenticatedUser().validateHasReadPermission("view_pendientes");
        PendingFlowBlueprintData data = readService.retrieveOne(id);
        return toApiJsonSerializer.serialize(data);
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String create(@Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("create_pending_flow_blueprint");
        PendingFlowBlueprintData data = writeService.create(apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }

    @PUT
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String update(@PathParam("id") Long id, @Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("update_pending_flow_blueprint");
        PendingFlowBlueprintData data = writeService.update(id, apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }
}
