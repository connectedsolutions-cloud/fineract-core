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
package org.apache.fineract.portfolio.mobilecollection.service;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.staff.domain.Staff;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.organisation.staff.exception.StaffNotFoundException;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientRepository;
import org.apache.fineract.portfolio.client.exception.ClientNotFoundException;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteData;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteRequest;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionRouteTemplateData;
import org.apache.fineract.portfolio.mobilecollection.data.MobileCollectionStaffOptionData;
import org.apache.fineract.portfolio.mobilecollection.domain.MobileCollectionRoute;
import org.apache.fineract.portfolio.mobilecollection.domain.MobileCollectionRouteRepository;
import org.apache.fineract.portfolio.mobilecollection.exception.MobileCollectionRouteNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class MobileCollectionRouteServiceImpl implements MobileCollectionRouteService {

    private final MobileCollectionRouteRepository routeRepository;
    private final StaffRepository staffRepository;
    private final ClientRepository clientRepository;

    @PersistenceContext
    private EntityManager entityManager;

    @Override
    @Transactional(readOnly = true)
    public List<MobileCollectionRouteData> retrieveAll() {
        return routeRepository.findAllFetched().stream().map(route -> MobileCollectionRouteData.from(route, false)).toList();
    }

    @Override
    @Transactional(readOnly = true)
    public MobileCollectionRouteData retrieveOne(final Long routeId) {
        return MobileCollectionRouteData.from(findRoute(routeId), true);
    }

    @Override
    @Transactional(readOnly = true)
    public MobileCollectionRouteTemplateData retrieveTemplate() {
        final MobileCollectionRouteTemplateData template = new MobileCollectionRouteTemplateData();
        final List<MobileCollectionStaffOptionData> options = staffRepository.findAll().stream().filter(staff -> staff.getId() != null)
                .map(MobileCollectionStaffOptionData::from)
                .sorted(Comparator.comparing(MobileCollectionStaffOptionData::getDisplayName,
                        Comparator.nullsLast(String.CASE_INSENSITIVE_ORDER)))
                .toList();
        template.setStaffOptions(options);
        return template;
    }

    @Override
    @Transactional
    public MobileCollectionRouteData create(final MobileCollectionRouteRequest request) {
        final Staff staff = resolveStaff(request);
        final Set<Long> clientIds = uniqueClientIds(request);
        final MobileCollectionRoute route = MobileCollectionRoute.createNative(validateRouteName(request), staff, officeOf(staff));
        for (final Long clientId : clientIds) {
            route.addAssignment(loadClient(clientId));
        }
        return MobileCollectionRouteData.from(routeRepository.saveAndFlush(route), true);
    }

    @Override
    @Transactional
    public MobileCollectionRouteData update(final Long routeId, final MobileCollectionRouteRequest request) {
        final MobileCollectionRoute route = findRoute(routeId);
        final Staff staff = resolveStaff(request);
        final Set<Long> clientIds = uniqueClientIds(request);
        route.updateOperationalFields(validateRouteName(request), staff, officeOf(staff));
        route.removeAssignmentsNotIn(clientIds);
        for (final Long clientId : clientIds) {
            if (!route.hasClient(clientId)) {
                route.addAssignment(loadClient(clientId));
            }
        }
        return MobileCollectionRouteData.from(routeRepository.saveAndFlush(route), true);
    }

    @Override
    @Transactional
    public void delete(final Long routeId) {
        final MobileCollectionRoute route = findRoute(routeId);
        // EclipseLink native SQL does not bind JPA named parameters; use a positional placeholder.
        entityManager.createNativeQuery("DELETE FROM credesal_mobile_collection_account_assignment WHERE route_id = ?")
                .setParameter(1, routeId).executeUpdate();
        routeRepository.delete(route);
    }

    private MobileCollectionRoute findRoute(final Long routeId) {
        return routeRepository.findByIdFetched(routeId).orElseThrow(() -> new MobileCollectionRouteNotFoundException(routeId));
    }

    private String validateRouteName(final MobileCollectionRouteRequest request) {
        if (request == null || StringUtils.isBlank(request.getRouteName())) {
            throw new GeneralPlatformDomainRuleException("error.msg.mobile.collection.route.name.required", "Route name is required");
        }
        return request.getRouteName().trim();
    }

    private Staff resolveStaff(final MobileCollectionRouteRequest request) {
        if (request == null || request.getResponsibleStaffId() == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.mobile.collection.route.staff.required",
                    "Responsible employee is required");
        }
        return staffRepository.findById(request.getResponsibleStaffId())
                .orElseThrow(() -> new StaffNotFoundException(request.getResponsibleStaffId()));
    }

    private Office officeOf(final Staff staff) {
        return staff.getOffice();
    }

    private Set<Long> uniqueClientIds(final MobileCollectionRouteRequest request) {
        final List<Long> clientIds = request.getClientIds() == null ? List.of() : request.getClientIds();
        final List<Long> nonNullIds = new ArrayList<>();
        for (final Long clientId : clientIds) {
            if (clientId != null) {
                nonNullIds.add(clientId);
            }
        }
        final Set<Long> uniqueIds = new LinkedHashSet<>(nonNullIds);
        if (uniqueIds.size() != nonNullIds.size()) {
            throw new GeneralPlatformDomainRuleException("error.msg.mobile.collection.route.duplicate.client",
                    "A client cannot be added twice to the same route");
        }
        return uniqueIds;
    }

    private Client loadClient(final Long clientId) {
        return clientRepository.findById(clientId).orElseThrow(() -> new ClientNotFoundException(clientId));
    }
}
