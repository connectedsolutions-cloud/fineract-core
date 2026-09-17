/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.commands.domain.CommandWrapper;
import org.apache.fineract.commands.service.CommandWrapperBuilder;
import org.apache.fineract.commands.service.PortfolioCommandSourceWritePlatformService;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.shareaccounts.service.ShareYieldService;
import org.springframework.stereotype.Component;

@Path("/v1/shareyield")
@Component
@Tag(name = "Share Yield", description = "Contractual daily yield accrual and unpaid-yield balances for native share accounts")
@RequiredArgsConstructor
public class ShareYieldApiResource {

    private final PlatformSecurityContext securityContext;
    private final PortfolioCommandSourceWritePlatformService commandService;
    private final ShareYieldService shareYieldService;

    @GET
    @Path("products/{productId}")
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Retrieve native share-yield configuration")
    public Map<String, Object> retrieveProduct(@PathParam("productId") Long productId) {
        securityContext.authenticatedUser();
        return shareYieldService.retrieveProductConfiguration(productId);
    }

    @POST
    @Path("products/{productId}")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Create or replace native share-yield configuration")
    public CommandProcessingResult configureProduct(@PathParam("productId") Long productId, String json) {
        securityContext.authenticatedUser();
        CommandWrapper command = new CommandWrapperBuilder().createProductCommand("share", "yieldconfig", productId).withJson(json).build();
        return commandService.logCommandSource(command);
    }

    @GET
    @Path("accounts/{accountId}")
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Retrieve native share-yield accruals and unpaid balance")
    public Map<String, Object> retrieveAccount(@PathParam("accountId") Long accountId) {
        securityContext.authenticatedUser();
        return shareYieldService.retrieveAccountYield(accountId);
    }
}
