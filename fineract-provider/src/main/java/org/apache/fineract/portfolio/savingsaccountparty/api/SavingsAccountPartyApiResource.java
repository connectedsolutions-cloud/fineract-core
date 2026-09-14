/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information regarding copyright ownership. The ASF licenses this file to you under
 * the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain
 * a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS"
 * BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language
 * governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.savingsaccountparty.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonRequest;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryRequest;
import org.apache.fineract.portfolio.savingsaccountparty.service.SavingsAccountPartyService;
import org.springframework.stereotype.Component;

@Path("/v1/depositaccounts/{accountId}")
@Component
@RequiredArgsConstructor
public class SavingsAccountPartyApiResource {

    private static final String SAVINGS_ACCOUNT_RESOURCE = "SAVINGSACCOUNT";
    private final PlatformSecurityContext context;
    private final SavingsAccountPartyService service;

    @GET
    @Path("beneficiaries")
    @Produces({ MediaType.APPLICATION_JSON })
    public List<SavingsBeneficiaryData> retrieveBeneficiaries(@PathParam("accountId") final Long accountId) {
        context.authenticatedUser().validateHasReadPermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.retrieveBeneficiaries(accountId);
    }

    @PUT
    @Path("beneficiaries")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public List<SavingsBeneficiaryData> replaceBeneficiaries(@PathParam("accountId") final Long accountId,
            final List<SavingsBeneficiaryRequest> requests) {
        context.authenticatedUser().validateHasUpdatePermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.replaceBeneficiaries(accountId, requests);
    }

    @GET
    @Path("authorized-persons")
    @Produces({ MediaType.APPLICATION_JSON })
    public List<SavingsAuthorizedPersonData> retrieveAuthorizedPersons(@PathParam("accountId") final Long accountId) {
        context.authenticatedUser().validateHasReadPermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.retrieveAuthorizedPersons(accountId);
    }

    @PUT
    @Path("authorized-persons")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public List<SavingsAuthorizedPersonData> replaceAuthorizedPersons(@PathParam("accountId") final Long accountId,
            final List<SavingsAuthorizedPersonRequest> requests) {
        context.authenticatedUser().validateHasUpdatePermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.replaceAuthorizedPersons(accountId, requests);
    }

    @POST
    @Path("authorized-persons")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public SavingsAuthorizedPersonData createAuthorizedPerson(@PathParam("accountId") final Long accountId,
            final SavingsAuthorizedPersonRequest request) {
        context.authenticatedUser().validateHasUpdatePermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.createAuthorizedPerson(accountId, request);
    }

    @PUT
    @Path("authorized-persons/{personId}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public SavingsAuthorizedPersonData updateAuthorizedPerson(@PathParam("accountId") final Long accountId,
            @PathParam("personId") final Long personId, final SavingsAuthorizedPersonRequest request) {
        context.authenticatedUser().validateHasUpdatePermission(SAVINGS_ACCOUNT_RESOURCE);
        return service.updateAuthorizedPerson(accountId, personId, request);
    }

    @DELETE
    @Path("authorized-persons/{personId}")
    public void deleteAuthorizedPerson(@PathParam("accountId") final Long accountId, @PathParam("personId") final Long personId) {
        context.authenticatedUser().validateHasUpdatePermission(SAVINGS_ACCOUNT_RESOURCE);
        service.deleteAuthorizedPerson(accountId, personId);
    }
}
