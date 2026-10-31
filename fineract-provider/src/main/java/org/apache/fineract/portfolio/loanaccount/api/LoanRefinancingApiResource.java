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
package org.apache.fineract.portfolio.loanaccount.api;

import com.google.gson.Gson;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanaccount.service.LoanRefinancingOperations;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@Path("/v1/loans")
public class LoanRefinancingApiResource {

    private final LoanRefinancingOperations operations;
    private final PlatformSecurityContext security;

    @GET
    @Path("{loanId}/refinancing")
    @Produces(MediaType.APPLICATION_JSON)
    public String read(@PathParam("loanId") Long loanId) {
        security.authenticatedUser().validateHasReadPermission("LOAN");
        return new Gson().toJson(operations.read(loanId));
    }

    @GET
    @Path("refinancing-payouts")
    @Produces(MediaType.APPLICATION_JSON)
    public String pending(@QueryParam("officeId") Long officeId) {
        security.authenticatedUser().validateHasReadPermission("LOAN");
        return new Gson().toJson(operations.pending(officeId));
    }
}
