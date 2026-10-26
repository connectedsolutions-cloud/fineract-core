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

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.loanaccount.service.FinalLoanMetricAlignmentService;
import org.springframework.stereotype.Component;

@Path("/v1/loans/{loanId}/migration-metrics")
@Component
@RequiredArgsConstructor
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class FinalLoanMetricAlignmentApiResource {

    private final FinalLoanMetricAlignmentService service;

    @GET
    public Map<String, Object> read(@PathParam("loanId") long loanId, @QueryParam("cutoffDate") String cutoffDate,
            @QueryParam("insuranceChargeId") long insuranceId, @QueryParam("recurringInsuranceChargeId") long recurringId) {
        return service.read(loanId, cutoffDate, insuranceId, recurringId);
    }

    @POST
    public Map<String, Object> align(@PathParam("loanId") long loanId, String json) {
        return service.align(loanId, json);
    }
}
