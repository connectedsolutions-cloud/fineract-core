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
package org.apache.fineract.organisation.staff.data;

import java.io.Serial;
import java.io.Serializable;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import lombok.Getter;
import org.apache.fineract.organisation.office.data.OfficeData;

/**
 * Immutable data object representing staff data.
 */
@Getter
public final class StaffData implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    private final Long id;
    private final String externalId;
    private final String firstname;
    private final String lastname;
    private final String displayName;
    private final String mobileNo;
    private final String emailAddress;
    private final Long officeId; // Backward compatibility: represents primary office
    private final String officeName; // Backward compatibility: represents primary office name
    private final List<Long> officeIds; // All assigned office IDs
    private final Collection<OfficeData> offices; // All assigned office details
    private final Boolean isLoanOfficer;
    private final Boolean isActive;
    private final LocalDate joiningDate;

    // import fields
    private transient Integer rowIndex;
    private String dateFormat;
    private String locale;

    public static StaffData importInstance(String externalId, String firstname, String lastname, String mobileNo, Long officeId,
            Boolean isLoanOfficer, Boolean isActive, LocalDate joinedOnDate, Integer rowIndex, String locale, String dateFormat) {
        return new StaffData(externalId, firstname, lastname, mobileNo, officeId, isLoanOfficer, isActive, joinedOnDate, rowIndex, locale,
                dateFormat);

    }

    private StaffData(String externalId, String firstname, String lastname, String mobileNo, Long officeId, Boolean isLoanOfficer,
            Boolean isActive, LocalDate joiningDate, Integer rowIndex, String locale, String dateFormat) {

        this.externalId = externalId;
        this.firstname = firstname;
        this.lastname = lastname;
        this.mobileNo = mobileNo;
        this.emailAddress = null;
        this.officeId = officeId;
        this.officeIds = officeId != null ? List.of(officeId) : null;
        this.offices = null;
        this.isLoanOfficer = isLoanOfficer;
        this.isActive = isActive;
        this.joiningDate = joiningDate;
        this.rowIndex = rowIndex;
        this.dateFormat = dateFormat;
        this.locale = locale;
        this.allowedOffices = null;
        this.id = null;
        this.officeName = null;
        this.displayName = null;
    }

    public Integer getRowIndex() {
        return rowIndex;
    }

    @SuppressWarnings("unused")
    private final Collection<OfficeData> allowedOffices;

    public static StaffData templateData(final StaffData staff, final Collection<OfficeData> allowedOffices) {
        return new StaffData(staff.id, staff.firstname, staff.lastname, staff.displayName, staff.officeId, staff.officeName,
                staff.officeIds, staff.offices, staff.isLoanOfficer, staff.externalId, staff.mobileNo, staff.emailAddress, allowedOffices, staff.isActive,
                staff.joiningDate);
    }

    public static StaffData lookup(final Long id, final String displayName) {
        return new StaffData(id, null, null, displayName, null, null, null, null, null, null, null, null, null, null, null);
    }

    // Backward compatibility method - single office
    public static StaffData instance(final Long id, final String firstname, final String lastname, final String displayName,
            final Long officeId, final String officeName, final Boolean isLoanOfficer, final String externalId, final String mobileNo,
            final String emailAddress,
            final boolean isActive, final LocalDate joiningDate) {
        final List<Long> officeIdsList = officeId != null ? List.of(officeId) : null;
        return new StaffData(id, firstname, lastname, displayName, officeId, officeName, officeIdsList, null, isLoanOfficer, externalId,
                mobileNo, emailAddress, null, isActive, joiningDate);
    }

    // New method with multiple offices support
    public static StaffData instance(final Long id, final String firstname, final String lastname, final String displayName,
            final Long officeId, final String officeName, final List<Long> officeIds, final Collection<OfficeData> offices,
            final Boolean isLoanOfficer, final String externalId, final String mobileNo, final String emailAddress, final boolean isActive,
            final LocalDate joiningDate) {
        return new StaffData(id, firstname, lastname, displayName, officeId, officeName, officeIds, offices, isLoanOfficer, externalId,
                mobileNo, emailAddress, null, isActive, joiningDate);
    }

    private StaffData(final Long id, final String firstname, final String lastname, final String displayName, final Long officeId,
            final String officeName, final List<Long> officeIds, final Collection<OfficeData> offices, final Boolean isLoanOfficer,
            final String externalId, final String mobileNo, final String emailAddress, final Collection<OfficeData> allowedOffices, final Boolean isActive,
            final LocalDate joiningDate) {
        this.id = id;
        this.firstname = firstname;
        this.lastname = lastname;
        this.displayName = displayName;
        this.officeName = officeName;
        this.officeId = officeId != null ? officeId : (officeIds != null && !officeIds.isEmpty() ? officeIds.get(0) : null);
        this.officeIds = officeIds != null ? new ArrayList<>(officeIds) : (officeId != null ? List.of(officeId) : null);
        this.offices = offices != null ? new ArrayList<>(offices) : null;
        this.isLoanOfficer = isLoanOfficer;
        this.externalId = externalId;
        this.mobileNo = mobileNo;
        this.emailAddress = emailAddress;
        this.allowedOffices = allowedOffices;
        this.isActive = isActive;
        this.joiningDate = joiningDate;
    }

    public Long getId() {
        return this.id;
    }

    public String getDisplayName() {
        return this.displayName;
    }

    public String getEmailAddress() {
        return this.emailAddress;
    }

    public String getFirstname() {
        return this.firstname;
    }

    public String getLastname() {
        return this.lastname;
    }

    public String getOfficeName() {
        return this.officeName;
    }

    public LocalDate getJoiningDate() {
        return this.joiningDate;
    }

    public Long getOfficeId() {
        return this.officeId;
    }

    public List<Long> getOfficeIds() {
        return this.officeIds != null ? new ArrayList<>(this.officeIds) : null;
    }

    public Collection<OfficeData> getOffices() {
        return this.offices != null ? new ArrayList<>(this.offices) : null;
    }
}
