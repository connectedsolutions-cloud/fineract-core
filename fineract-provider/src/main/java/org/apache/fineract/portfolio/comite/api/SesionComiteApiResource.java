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
package org.apache.fineract.portfolio.comite.api;

import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
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
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.commands.domain.CommandWrapper;
import org.apache.fineract.commands.service.CommandWrapperBuilder;
import org.apache.fineract.commands.service.PortfolioCommandSourceWritePlatformService;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.serialization.DefaultToApiJsonSerializer;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.comite.data.SesionComiteData;
import org.apache.fineract.portfolio.comite.data.SesionComiteRequest;
import org.apache.fineract.portfolio.comite.service.SesionComiteReadPlatformService;
import org.apache.fineract.portfolio.loanaccount.data.LoanAccountData;
import org.springframework.stereotype.Component;

@Path("/v1/comite-otorgamiento")
@Component
@Tag(name = "Sesion Comite", description = "")
@RequiredArgsConstructor
public class SesionComiteApiResource {

    private static final String RESOURCE_NAME_FOR_PERMISSIONS = "LOAN_COMITEE";

    private final PlatformSecurityContext context;
    private final SesionComiteReadPlatformService readPlatformService;
    private final DefaultToApiJsonSerializer<SesionComiteData> toApiJsonSerializer;
    private final DefaultToApiJsonSerializer<LoanAccountData> toLoanJsonSerializer;
    private final PortfolioCommandSourceWritePlatformService commandsSourceWritePlatformService;

    @GET
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveAllSessions(@Context final UriInfo uriInfo) {
        context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
        final List<SesionComiteData> sessions = readPlatformService.retrieveAllSessions();
        return this.toApiJsonSerializer.serialize(sessions);
    }

    @GET
    @Path("{sessionId}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrieveOneSession(@PathParam("sessionId") final Long sessionId, @Context final UriInfo uriInfo) {
        context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
        final SesionComiteData session = readPlatformService.retrieveOneSession(sessionId);
        return this.toApiJsonSerializer.serialize(session);
    }

    @GET
    @Path("pending-loans")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String retrievePendingLoans(@Context final UriInfo uriInfo,
            @QueryParam("current_office_id") @Parameter(description = "When set, limits loans to this office only instead of user's office hierarchy") final Long currentOfficeId) {
        context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
        final List<LoanAccountData> loans = readPlatformService.retrievePendingLoansForUser(currentOfficeId);
        return this.toLoanJsonSerializer.serialize(loans);
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String createSession(@QueryParam("command") final String commandParam,
            @Context final UriInfo uriInfo, final String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
        final CommandWrapper commandRequest = new CommandWrapperBuilder().createSesionComite()
                .withJson(apiRequestBodyAsJson).build();
        final CommandProcessingResult result = this.commandsSourceWritePlatformService.logCommandSource(commandRequest);
        return this.toApiJsonSerializer.serialize(result);
    }

    @PUT
    @Path("{sessionId}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String updateSession(@PathParam("sessionId") final Long sessionId,
            @Context final UriInfo uriInfo, final String apiRequestBodyAsJson) {
        context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
        final CommandWrapper commandRequest = new CommandWrapperBuilder().updateSesionComite(sessionId)
                .withJson(apiRequestBodyAsJson).build();
        final CommandProcessingResult result = this.commandsSourceWritePlatformService.logCommandSource(commandRequest);
        return this.toApiJsonSerializer.serialize(result);
    }

    @POST
    @Path("{sessionId}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public String handleCommands(@PathParam("sessionId") final Long sessionId,
            @QueryParam("command") final String commandParam, @Context final UriInfo uriInfo,
            final String apiRequestBodyAsJson) {

        CommandWrapper commandWrapper = null;
        if ("start".equalsIgnoreCase(commandParam)) {
            context.authenticatedUser().validateHasReadPermission("start_loan_comittee");
            commandWrapper = new CommandWrapperBuilder().startSesionComite(sessionId).withJson(apiRequestBodyAsJson).build();
        } else if ("apply".equalsIgnoreCase(commandParam)) {
            context.authenticatedUser().validateHasReadPermission("start_loan_comittee");
            commandWrapper = new CommandWrapperBuilder().applySesionComite(sessionId).withJson(apiRequestBodyAsJson).build();
        } else if ("updateSelections".equalsIgnoreCase(commandParam)) {
            context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
            commandWrapper = new CommandWrapperBuilder().updateSelectionsSesionComite(sessionId).withJson(apiRequestBodyAsJson)
                    .build();
        } else if ("submit".equalsIgnoreCase(commandParam)) {
            context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
            commandWrapper = new CommandWrapperBuilder().submitSesionComite(sessionId).withJson(apiRequestBodyAsJson).build();
        } else if ("close".equalsIgnoreCase(commandParam)) {
            context.authenticatedUser().validateHasReadPermission("start_loan_comittee");
            commandWrapper = new CommandWrapperBuilder().closeSesionComite(sessionId).withJson(apiRequestBodyAsJson).build();
        } else {
            context.authenticatedUser().validateHasReadPermission("see_loan_comittee");
            // Default to update for unknown commands
            commandWrapper = new CommandWrapperBuilder().updateSesionComite(sessionId).withJson(apiRequestBodyAsJson).build();
        }

        final CommandProcessingResult result = this.commandsSourceWritePlatformService.logCommandSource(commandWrapper);
        return this.toApiJsonSerializer.serialize(result);
    }
}
