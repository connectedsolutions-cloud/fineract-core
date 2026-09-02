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
package org.apache.fineract.portfolio.mobilecollection.domain;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.staff.domain.Staff;
import org.apache.fineract.portfolio.client.domain.Client;

@Entity
@Table(name = "credesal_mobile_collection_route")
@Getter
@Setter
@NoArgsConstructor
public class MobileCollectionRoute extends AbstractPersistableCustom<Long> {

    @Column(name = "arissto_route_id")
    private Integer arisstoRouteId;

    @Column(name = "arissto_company_id", length = 3)
    private String arisstoCompanyId;

    @Column(name = "arissto_branch_id", length = 3)
    private String arisstoBranchId;

    @ManyToOne
    @JoinColumn(name = "office_id")
    private Office office;

    @Column(name = "arissto_responsible_person_id", length = 5)
    private String arisstoResponsiblePersonId;

    @ManyToOne
    @JoinColumn(name = "responsible_staff_id")
    private Staff responsibleStaff;

    @Column(name = "route_name", length = 254)
    private String routeName;

    @Column(name = "source_status", length = 1)
    private String sourceStatus;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @OneToMany(mappedBy = "route", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<MobileCollectionAssignment> assignments = new ArrayList<>();

    public static MobileCollectionRoute createNative(final String routeName, final Staff responsibleStaff, final Office office) {
        final MobileCollectionRoute route = new MobileCollectionRoute();
        route.routeName = routeName;
        route.responsibleStaff = responsibleStaff;
        route.office = office;
        route.createdAt = DateUtils.getLocalDateTimeOfTenant();
        return route;
    }

    public void updateOperationalFields(final String routeName, final Staff responsibleStaff, final Office office) {
        this.routeName = routeName;
        this.responsibleStaff = responsibleStaff;
        this.office = office;
        this.updatedAt = DateUtils.getLocalDateTimeOfTenant();
    }

    public void addAssignment(final Client client) {
        final MobileCollectionAssignment assignment = MobileCollectionAssignment.createNative(this, client);
        this.assignments.add(assignment);
    }

    public void removeAssignmentsNotIn(final java.util.Set<Long> clientIds) {
        this.assignments.removeIf(assignment -> assignment.getClient() == null || !clientIds.contains(assignment.getClient().getId()));
    }

    public boolean hasClient(final Long clientId) {
        return this.assignments.stream()
                .anyMatch(assignment -> assignment.getClient() != null && clientId.equals(assignment.getClient().getId()));
    }
}
