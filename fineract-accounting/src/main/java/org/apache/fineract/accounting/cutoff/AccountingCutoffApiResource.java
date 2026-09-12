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
package org.apache.fineract.accounting.cutoff;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Path("/v1/accountingcutoff")
@Component
@Tag(name = "Accounting Cutoff", description = "Tenant accounting cutover configuration and lifecycle")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
@RequiredArgsConstructor
public class AccountingCutoffApiResource {

    private final AccountingCutoffConfigurationService service;

    @GET
    @Operation(summary = "Retrieve the tenant accounting cutoff")
    public AccountingCutoffConfigurationData retrieve() {
        return service.retrieve();
    }

    @POST
    @Operation(summary = "Create or update the draft accounting cutoff")
    public AccountingCutoffConfigurationData configureDraft(AccountingCutoffConfigurationRequest request) {
        return service.configureDraft(request);
    }

    @POST
    @Path("activate")
    @Operation(summary = "Activate the accounting cutoff")
    public AccountingCutoffConfigurationData activate() {
        return service.activate();
    }

    @POST
    @Path("seal")
    @Operation(summary = "Permanently seal migration mode")
    public AccountingCutoffConfigurationData seal() {
        return service.seal();
    }
}
