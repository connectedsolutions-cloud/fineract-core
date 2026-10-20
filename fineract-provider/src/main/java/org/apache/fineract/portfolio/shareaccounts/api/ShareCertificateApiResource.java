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
package org.apache.fineract.portfolio.shareaccounts.api;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.shareaccounts.service.ShareCertificateService;
import org.springframework.stereotype.Component;

@Path("/v1/sharecertificates")
@Component
@Tag(name = "Share Certificates", description = "Common and preferred share certificates for a member share account")
@RequiredArgsConstructor
public class ShareCertificateApiResource {

    private final PlatformSecurityContext securityContext;
    private final ShareCertificateService shareCertificateService;

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "List share certificates for a client or one share account")
    public List<Map<String, Object>> list(@QueryParam("clientId") final Long clientId,
            @QueryParam("shareAccountId") final Long shareAccountId) {
        this.securityContext.authenticatedUser().validateHasReadPermission("SHAREACCOUNT");
        if (shareAccountId != null) {
            return this.shareCertificateService.listByShareAccount(shareAccountId);
        }
        if (clientId != null) {
            return this.shareCertificateService.summariesByClient(clientId);
        }
        throw new PlatformApiDataValidationException(List.of(ApiParameterError.parameterError("validation.msg.share.certificate.scope",
                "clientId or shareAccountId is required.", "clientId")));
    }

    @GET
    @Path("{certificateId}")
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Retrieve one share certificate, including the print payload")
    public Map<String, Object> retrieve(@PathParam("certificateId") final Long certificateId) {
        this.securityContext.authenticatedUser().validateHasReadPermission("SHAREACCOUNT");
        return this.shareCertificateService.printPayload(certificateId);
    }

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Open another certificate on an existing share account")
    public CommandProcessingResult openAdditional(@QueryParam("shareAccountId") final Long shareAccountId, final String json) {
        this.securityContext.authenticatedUser().validateHasCreatePermission("SHAREACCOUNT");
        return this.shareCertificateService.openAdditional(shareAccountId, json);
    }

    @POST
    @Path("{certificateId}")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    @Operation(summary = "Emit a certificate or record that it was printed")
    public CommandProcessingResult act(@PathParam("certificateId") final Long certificateId, @QueryParam("command") final String command) {
        this.securityContext.authenticatedUser().validateHasUpdatePermission("SHAREACCOUNT");
        if ("emit".equalsIgnoreCase(command)) {
            return this.shareCertificateService.emit(certificateId);
        }
        if ("print".equalsIgnoreCase(command)) {
            return this.shareCertificateService.markPrinted(certificateId);
        }
        throw new PlatformApiDataValidationException(List.of(
                ApiParameterError.parameterError("validation.msg.share.certificate.command", "command must be emit or print.", "command")));
    }
}
