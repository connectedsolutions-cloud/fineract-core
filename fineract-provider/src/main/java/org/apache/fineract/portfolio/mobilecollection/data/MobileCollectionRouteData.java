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
package org.apache.fineract.portfolio.mobilecollection.data;

import java.util.ArrayList;
import java.util.List;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.portfolio.mobilecollection.domain.MobileCollectionAssignment;
import org.apache.fineract.portfolio.mobilecollection.domain.MobileCollectionRoute;

@Getter
@Setter
@NoArgsConstructor
public class MobileCollectionRouteData {

    private Long id;
    private String routeName;
    private Long responsibleStaffId;
    private String responsibleStaffName;
    private Long officeId;
    private String officeName;
    private Integer clientCount;
    private Integer arisstoRouteId;
    private List<MobileCollectionClientData> clients = new ArrayList<>();

    public static MobileCollectionRouteData from(final MobileCollectionRoute route, final boolean includeClients) {
        final MobileCollectionRouteData data = new MobileCollectionRouteData();
        data.id = route.getId();
        data.routeName = route.getRouteName();
        data.arisstoRouteId = route.getArisstoRouteId();
        if (route.getResponsibleStaff() != null) {
            data.responsibleStaffId = route.getResponsibleStaff().getId();
            data.responsibleStaffName = route.getResponsibleStaff().getDisplayName();
        }
        if (route.getOffice() != null) {
            data.officeId = route.getOffice().getId();
            data.officeName = route.getOffice().getName();
        }
        final List<MobileCollectionAssignment> assignments = route.getAssignments() == null ? List.of() : route.getAssignments();
        data.clientCount = assignments.size();
        if (includeClients) {
            for (final MobileCollectionAssignment assignment : assignments) {
                if (assignment.getClient() != null) {
                    data.clients.add(MobileCollectionClientData.from(assignment.getClient()));
                }
            }
        }
        return data;
    }
}
