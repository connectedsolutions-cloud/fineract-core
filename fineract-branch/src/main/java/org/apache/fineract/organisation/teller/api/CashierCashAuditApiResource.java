/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.organisation.teller.api;

import io.swagger.v3.oas.annotations.Operation;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.organisation.teller.data.CashierCashAuditData;
import org.apache.fineract.organisation.teller.service.CashierCashAuditService;
import org.springframework.stereotype.Component;

@Path("/v1/tellers/{tellerId}/cashiers/{cashierId}/cash-audit")
@Component
@RequiredArgsConstructor
public class CashierCashAuditApiResource {

    private final CashierCashAuditService auditService;

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Read-only cashier cash attribution audit", description = "Diagnostic evidence; does not authorize session close")
    public CashierCashAuditData audit(@PathParam("tellerId") final Long tellerId, @PathParam("cashierId") final Long cashierId,
            @QueryParam("currencyCode") final String currencyCode) {
        if (currencyCode == null || currencyCode.isBlank()) {
            throw new WebApplicationException("currencyCode is required", 400);
        }
        return auditService.audit(tellerId, cashierId, currencyCode);
    }
}
