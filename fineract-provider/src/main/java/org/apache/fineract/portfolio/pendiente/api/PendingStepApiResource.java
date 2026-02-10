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
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.UriInfo;
import java.util.Arrays;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.serialization.DefaultToApiJsonSerializer;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.pendiente.data.PendingStepData;
import org.apache.fineract.portfolio.pendiente.service.PendingStepReadPlatformService;
import org.apache.fineract.portfolio.pendiente.service.PendingStepWritePlatformService;
import org.springframework.stereotype.Component;

@Path("/v1/pending-steps")
@Component
@RequiredArgsConstructor
public class PendingStepApiResource {

    private final PlatformSecurityContext context;
    private final PendingStepReadPlatformService readService;
    private final PendingStepWritePlatformService writeService;
    private final DefaultToApiJsonSerializer<PendingStepData> toApiJsonSerializer;

    @GET
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveAll(@Context UriInfo uriInfo, @QueryParam("flowId") Long flowId,
            @QueryParam("mySteps") Boolean mySteps) {
        context.authenticatedUser().validateHasReadPermission("view_pendientes");
        if (Boolean.TRUE.equals(mySteps)) {
            Long userId = context.authenticatedUser().getId();
            List<PendingStepData> data = readService.retrieveMySteps(userId, Arrays.asList("open", "pending"));
            return toApiJsonSerializer.serialize(data);
        }
        if (flowId != null) {
            List<PendingStepData> data = readService.retrieveByFlowId(flowId);
            return toApiJsonSerializer.serialize(data);
        }
        return toApiJsonSerializer.serialize(List.of());
    }

    @GET
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveOne(@PathParam("id") Long id, @Context UriInfo uriInfo) {
        context.authenticatedUser().validateHasReadPermission("view_pendientes");
        PendingStepData data = readService.retrieveOne(id);
        return toApiJsonSerializer.serialize(data);
    }

    @PUT
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String update(@PathParam("id") Long id, @Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("update_pending_step");
        PendingStepData data = writeService.update(id, apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }

    @POST
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String complete(@PathParam("id") Long id, @QueryParam("command") String command,
            @Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("complete_pending_step");
        if (!"complete".equalsIgnoreCase(command)) {
            return toApiJsonSerializer.serialize(writeService.update(id, apiRequestBodyAsJson));
        }
        PendingStepData data = writeService.complete(id, apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }
}
