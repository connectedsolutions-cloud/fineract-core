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
package org.apache.fineract.accounting.reporting;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import java.time.LocalDate;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.springframework.stereotype.Component;

@Path("/v1/credesalfinancialreports")
@Component
@Tag(name = "Credesal Financial Reports", description = "Dimension-aware reports calculated directly from native journal rows")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
@RequiredArgsConstructor
public class CredesalFinancialReportsApiResource {

    private final CredesalFinancialReportService service;

    @GET
    @Path("{reportType}")
    @Operation(summary = "Run a native Credesal financial report")
    public CredesalFinancialReportData run(@PathParam("reportType") String reportType, @QueryParam("fromDate") String fromDate,
            @QueryParam("toDate") String toDate, @QueryParam("officeExternalId") String officeExternalId,
            @QueryParam("closingMode") String closingMode, @QueryParam("includeZero") boolean includeZero) {
        if (StringUtils.isBlank(toDate)) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.to.date.required", "toDate is required");
        }
        try {
            LocalDate parsedFromDate = StringUtils.isBlank(fromDate) ? null : LocalDate.parse(fromDate);
            return service.run(reportType, parsedFromDate, LocalDate.parse(toDate), StringUtils.trimToNull(officeExternalId),
                    StringUtils.defaultIfBlank(closingMode, "post-closing"), includeZero);
        } catch (java.time.format.DateTimeParseException exception) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.report.date.invalid",
                    "Report dates must use ISO yyyy-MM-dd format", exception);
        }
    }
}
