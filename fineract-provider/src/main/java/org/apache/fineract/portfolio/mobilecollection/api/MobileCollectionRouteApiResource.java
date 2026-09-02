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
package org.apache.fineract.portfolio.mobilecollection.api;

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
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteData;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteRequest;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteTemplateData;
import org.apache.fineract.portfolio.mobilecollection.service.MobileCollectionRouteService;
import org.springframework.stereotype.Component;

@Path("/v1/mobile-collection-routes")
@Component
@RequiredArgsConstructor
public class MobileCollectionRouteApiResource {

    private static final String RESOURCE_NAME = "MOBILECOLLECTIONROUTE";

    private final PlatformSecurityContext context;
    private final MobileCollectionRouteService routeService;

    @GET
    @Produces({ MediaType.APPLICATION_JSON })
    public List<MobileCollectionRouteData> retrieveAll() {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return routeService.retrieveAll();
    }

    @GET
    @Path("template")
    @Produces({ MediaType.APPLICATION_JSON })
    public MobileCollectionRouteTemplateData retrieveTemplate() {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return routeService.retrieveTemplate();
    }

    @GET
    @Path("{routeId}")
    @Produces({ MediaType.APPLICATION_JSON })
    public MobileCollectionRouteData retrieveOne(@PathParam("routeId") final Long routeId) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return routeService.retrieveOne(routeId);
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public MobileCollectionRouteData create(final MobileCollectionRouteRequest request) {
        context.authenticatedUser().validateHasCreatePermission(RESOURCE_NAME);
        return routeService.create(request);
    }

    @PUT
    @Path("{routeId}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public MobileCollectionRouteData update(@PathParam("routeId") final Long routeId, final MobileCollectionRouteRequest request) {
        context.authenticatedUser().validateHasUpdatePermission(RESOURCE_NAME);
        return routeService.update(routeId, request);
    }

    @DELETE
    @Path("{routeId}")
    @Produces({ MediaType.APPLICATION_JSON })
    public void delete(@PathParam("routeId") final Long routeId) {
        context.authenticatedUser().validateHasDeletePermission(RESOURCE_NAME);
        routeService.delete(routeId);
    }
}
