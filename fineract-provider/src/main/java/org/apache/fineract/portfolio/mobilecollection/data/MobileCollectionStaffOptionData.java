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

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.organisation.staff.domain.Staff;

@Getter
@Setter
@NoArgsConstructor
public class MobileCollectionStaffOptionData {

    private Long id;
    private String displayName;

    public static MobileCollectionStaffOptionData from(final Staff staff) {
        final MobileCollectionStaffOptionData data = new MobileCollectionStaffOptionData();
        data.id = staff.getId();
        data.displayName = staffDisplayName(staff);
        return data;
    }

    private static String staffDisplayName(final Staff staff) {
        if (staff.getDisplayName() != null && !staff.getDisplayName().isBlank()) {
            return staff.getDisplayName();
        }
        final String lastname = staff.getLastname() == null ? "" : staff.getLastname().trim();
        final String firstname = staff.getFirstname() == null ? "" : staff.getFirstname().trim();
        if (!lastname.isEmpty() && !firstname.isEmpty()) {
            return lastname + ", " + firstname;
        }
        if (!lastname.isEmpty()) {
            return lastname;
        }
        if (!firstname.isEmpty()) {
            return firstname;
        }
        return staff.getId() == null ? "" : String.valueOf(staff.getId());
    }
}
