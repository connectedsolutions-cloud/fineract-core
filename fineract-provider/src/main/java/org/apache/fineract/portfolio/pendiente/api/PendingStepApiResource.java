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
            @QueryParam("mySteps") Boolean mySteps, @QueryParam("closed") Boolean closed,
            @QueryParam("officeId") Long officeId, @QueryParam("myFlowsOthersSteps") Boolean myFlowsOthersSteps) {
        context.authenticatedUser().validateHasPermissionTo("view_pendientes");
        Long userId = context.authenticatedUser().getId();
        if (Boolean.TRUE.equals(mySteps)) {
            if (Boolean.TRUE.equals(closed)) {
                List<PendingStepData> data = readService.retrieveMyCompletedSteps(userId, officeId);
                return toApiJsonSerializer.serialize(data);
            }
            List<PendingStepData> data = readService.retrieveMySteps(userId, Arrays.asList("open", "pending"),
                    officeId);
            return toApiJsonSerializer.serialize(data);
        }
        if (Boolean.TRUE.equals(myFlowsOthersSteps)) {
            if (Boolean.TRUE.equals(closed)) {
                List<PendingStepData> data = readService.retrieveCompletedStepsOnMyFlowsAssignedToOthers(userId, officeId);
                return toApiJsonSerializer.serialize(data);
            }
            List<PendingStepData> data = readService.retrieveStepsOnMyFlowsAssignedToOthers(userId,
                    Arrays.asList("open", "pending"), officeId);
            return toApiJsonSerializer.serialize(data);
        }
        if (flowId != null) {
            List<PendingStepData> data = readService.retrieveByFlowId(flowId, officeId);
            return toApiJsonSerializer.serialize(data);
        }
        if (officeId != null) {
            List<PendingStepData> data = readService.retrieveByOfficeId(officeId);
            return toApiJsonSerializer.serialize(data);
        }
        return toApiJsonSerializer.serialize(List.of());
    }

    @GET
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveOne(@PathParam("id") Long id, @Context UriInfo uriInfo) {
        context.authenticatedUser().validateHasPermissionTo("view_pendientes");
        PendingStepData data = readService.retrieveOne(id);
        return toApiJsonSerializer.serialize(data);
    }

    @PUT
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String update(@PathParam("id") Long id, @Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasPermissionTo("update_pending_step");
        PendingStepData data = writeService.update(id, apiRequestBodyAsJson);
        return toApiJsonSerializer.serialize(data);
    }

    @POST
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String complete(@PathParam("id") Long id, @QueryParam("command") String command,
            @Context UriInfo uriInfo, String apiRequestBodyAsJson) {
        if ("cancel".equalsIgnoreCase(command)) {
            context.authenticatedUser().validateHasPermissionTo("update_pending_step");
            PendingStepData data = writeService.cancel(id);
            return toApiJsonSerializer.serialize(data);
        }
        if ("complete".equalsIgnoreCase(command)) {
            context.authenticatedUser().validateHasPermissionTo("complete_pending_step");
            PendingStepData data = writeService.complete(id, apiRequestBodyAsJson);
            return toApiJsonSerializer.serialize(data);
        }
        context.authenticatedUser().validateHasPermissionTo("update_pending_step");
        return toApiJsonSerializer.serialize(writeService.update(id, apiRequestBodyAsJson));
    }
}
