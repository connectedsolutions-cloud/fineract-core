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
package org.apache.fineract.organisation.teller.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Collection;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.teller.data.CashierData;
import org.apache.fineract.organisation.teller.service.TellerManagementReadPlatformService;
import org.springframework.stereotype.Component;

@Path("/v1/cashiers")
@Component
@Tag(name = "Cashiers", description = "")
@RequiredArgsConstructor
public class CashierApiResource {

    private final TellerManagementReadPlatformService readPlatformService;

    @GET
    @Path("session")
    @Consumes({ MediaType.TEXT_HTML, MediaType.APPLICATION_JSON })
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Get active cashier session", description = "Returns the active (open) cashier session for the currently authenticated user. Returns 404 if no active session.")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "OK", content = @Content(schema = @Schema(implementation = CashierData.class))),
            @ApiResponse(responseCode = "404", description = "No active cashier session") })
    public Response getActiveCashierSession() {
        final CashierData session = readPlatformService.getActiveCashierSessionForCurrentUser();
        if (session == null) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }
        return Response.ok(session).build();
    }

    @GET
    @Consumes({ MediaType.TEXT_HTML, MediaType.APPLICATION_JSON })
    @Produces(MediaType.APPLICATION_JSON)
    public Collection<CashierData> getCashierData(@QueryParam("officeId") final Long officeId, @QueryParam("tellerId") final Long tellerId,
            @QueryParam("staffId") final Long staffId, @QueryParam("date") final String date) {
        final LocalDate dateRestriction = date != null ? LocalDate.parse(date, DateTimeFormatter.BASIC_ISO_DATE)
                : DateUtils.getBusinessLocalDate();
        return readPlatformService.getCashierData(officeId, tellerId, staffId, dateRestriction);
    }
}
