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
package org.apache.fineract.organisation.staff.domain;

import java.util.HashSet;
import java.util.Set;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.staff.exception.StaffNotFoundException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * <p>
 * Wrapper for {@link StaffRepository} that adds NULL checking and Error handling capabilities
 * </p>
 */
@Service
public class StaffRepositoryWrapper {

    private final StaffRepository repository;

    @Autowired
    public StaffRepositoryWrapper(final StaffRepository repository) {
        this.repository = repository;
    }

    public Staff findOneWithNotFoundDetection(final Long id) {
        return this.repository.findById(id).orElseThrow(() -> new StaffNotFoundException(id));
    }

    public Staff findByOfficeWithNotFoundDetection(final Long staffId, final Long officeId) {
        final Staff staff = this.repository.findByOffice(staffId, officeId);
        if (staff == null) {
            throw new StaffNotFoundException(staffId);
        }
        return staff;
    }

    public Staff findByOfficeHierarchyWithNotFoundDetection(final Long staffId, final String hierarchy) {
        final Staff staff = this.repository.findById(staffId).orElseThrow(() -> new StaffNotFoundException(staffId));
        final String staffhierarchy = staff.office().getHierarchy();
        if (!hierarchy.startsWith(staffhierarchy)) {
            throw new StaffNotFoundException(staffId);
        }
        return staff;
    }

    /**
     * Find staff by checking if they have any office in common with the provided set of office IDs. This method checks
     * both the primary office and the offices set (multi-office support).
     *
     * @param staffId
     *            the staff ID to find
     * @param officeIds
     *            the set of office IDs to check for overlap
     * @return the Staff entity if found and has at least one matching office
     * @throws StaffNotFoundException
     *             if staff not found or has no matching offices
     */
    public Staff findByAnyOfficeWithNotFoundDetection(final Long staffId, final Set<Long> officeIds) {
        final Staff staff = this.repository.findById(staffId).orElseThrow(() -> new StaffNotFoundException(staffId));

        // Collect all staff office IDs (primary + offices set)
        final Set<Long> staffOfficeIds = new HashSet<>();
        if (staff.getOffice() != null) {
            staffOfficeIds.add(staff.getOffice().getId());
        }
        for (final Office office : staff.getOffices()) {
            staffOfficeIds.add(office.getId());
        }

        // Check for any overlap
        final boolean hasMatchingOffice = officeIds.stream().anyMatch(staffOfficeIds::contains);

        if (!hasMatchingOffice) {
            throw new StaffNotFoundException(staffId);
        }

        return staff;
    }

    public void save(final Staff staff) {
        this.repository.save(staff);
    }
}
