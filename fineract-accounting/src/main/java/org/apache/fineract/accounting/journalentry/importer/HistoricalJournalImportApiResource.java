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
package org.apache.fineract.accounting.journalentry.importer;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Path("/v1/arisstohistoricaljournals")
@Component
@Tag(name = "Arissto Historical Journals", description = "Restricted atomic import and provenance access for historical Arissto GL")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
@RequiredArgsConstructor
public class HistoricalJournalImportApiResource {

    private final HistoricalJournalImportService service;

    @POST
    @Operation(summary = "Atomically import one complete historical Arissto journal")
    public HistoricalJournalImportResult importJournal(HistoricalJournalImportRequest request) {
        return service.importJournal(request);
    }

    @GET
    @Path("{companyId}/{branchId}/{periodId}/{journalId}/provenance")
    @Operation(summary = "Retrieve restricted lossless provenance for one imported journal")
    public HistoricalJournalProvenanceData retrieveProvenance(@PathParam("companyId") String companyId,
            @PathParam("branchId") String branchId, @PathParam("periodId") String periodId, @PathParam("journalId") String journalId) {
        return service.retrieve(companyId, branchId, periodId, journalId);
    }
}
