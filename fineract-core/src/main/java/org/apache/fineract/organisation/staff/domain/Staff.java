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

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import lombok.Getter;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.documentmanagement.domain.Image;
import org.apache.fineract.organisation.office.domain.Office;

@Getter
@Entity
@Table(name = "m_staff", uniqueConstraints = { @UniqueConstraint(columnNames = { "display_name" }, name = "display_name"),
        @UniqueConstraint(columnNames = { "external_id" }, name = "external_id_UNIQUE"),
        @UniqueConstraint(columnNames = { "mobile_no" }, name = "mobile_no_UNIQUE") })
public class Staff extends AbstractPersistableCustom<Long> {

    @Column(name = "firstname", length = 50)
    private String firstname;

    @Column(name = "lastname", length = 50)
    private String lastname;

    @Column(name = "display_name", length = 100)
    private String displayName;

    @Column(name = "mobile_no", length = 50, nullable = false, unique = true)
    private String mobileNo;

    @Column(name = "external_id", length = 100, unique = true)
    private String externalId;

    @Column(name = "email_address", length = 50, unique = true)
    private String emailAddress;

    @ManyToOne
    @JoinColumn(name = "office_id", nullable = true)
    private Office office;

    @ManyToMany(fetch = FetchType.LAZY)
    @JoinTable(name = "m_staff_office", joinColumns = @JoinColumn(name = "staff_id"), inverseJoinColumns = @JoinColumn(name = "office_id"))
    private Set<Office> offices = new HashSet<>();

    @Column(name = "is_loan_officer", nullable = false)
    private boolean loanOfficer;

    @Column(name = "organisational_role_enum")
    private Integer organisationalRoleType;

    @Column(name = "is_active", nullable = false)
    private boolean active;

    @Column(name = "joining_date")
    private LocalDate joiningDate;

    @ManyToOne
    @JoinColumn(name = "organisational_role_parent_staff_id")
    private Staff organisationalRoleParentStaff;

    @OneToOne(optional = true)
    @JoinColumn(name = "image_id")
    private Image image;

    public static Staff fromJson(final Office staffOffice, final JsonCommand command) {

        final String firstnameParamName = "firstname";
        final String firstname = command.stringValueOfParameterNamed(firstnameParamName);

        final String lastnameParamName = "lastname";
        final String lastname = command.stringValueOfParameterNamed(lastnameParamName);

        final String externalIdParamName = "externalId";
        final String externalId = command.stringValueOfParameterNamedAllowingNull(externalIdParamName);

        final String mobileNoParamName = "mobileNo";
        final String mobileNo = command.stringValueOfParameterNamedAllowingNull(mobileNoParamName);

        final String isLoanOfficerParamName = "isLoanOfficer";
        final boolean isLoanOfficer = command.booleanPrimitiveValueOfParameterNamed(isLoanOfficerParamName);

        final String isActiveParamName = "isActive";
        final Boolean isActive = command.booleanObjectValueOfParameterNamed(isActiveParamName);

        LocalDate joiningDate = null;

        final String joiningDateParamName = "joiningDate";
        if (command.hasParameter(joiningDateParamName)) {
            joiningDate = command.localDateValueOfParameterNamed(joiningDateParamName);
        }

        return new Staff(staffOffice, firstname, lastname, externalId, mobileNo, isLoanOfficer, isActive, joiningDate);
    }

    // Overloaded method to allow creating staff without primary office
    public static Staff fromJsonWithoutPrimaryOffice(final JsonCommand command) {
        final String firstnameParamName = "firstname";
        final String firstname = command.stringValueOfParameterNamed(firstnameParamName);

        final String lastnameParamName = "lastname";
        final String lastname = command.stringValueOfParameterNamed(lastnameParamName);

        final String externalIdParamName = "externalId";
        final String externalId = command.stringValueOfParameterNamedAllowingNull(externalIdParamName);

        final String mobileNoParamName = "mobileNo";
        final String mobileNo = command.stringValueOfParameterNamedAllowingNull(mobileNoParamName);

        final String isLoanOfficerParamName = "isLoanOfficer";
        final boolean isLoanOfficer = command.booleanPrimitiveValueOfParameterNamed(isLoanOfficerParamName);

        final String isActiveParamName = "isActive";
        final Boolean isActive = command.booleanObjectValueOfParameterNamed(isActiveParamName);

        LocalDate joiningDate = null;

        final String joiningDateParamName = "joiningDate";
        if (command.hasParameter(joiningDateParamName)) {
            joiningDate = command.localDateValueOfParameterNamed(joiningDateParamName);
        }

        return new Staff(null, firstname, lastname, externalId, mobileNo, isLoanOfficer, isActive, joiningDate);
    }

    protected Staff() {
        this.offices = new HashSet<>();
    }

    private Staff(final Office staffOffice, final String firstname, final String lastname, final String externalId, final String mobileNo,
            final boolean isLoanOfficer, final Boolean isActive, final LocalDate joiningDate) {
        this.office = staffOffice; // Can be null now
        this.firstname = StringUtils.defaultIfEmpty(firstname, null);
        this.lastname = StringUtils.defaultIfEmpty(lastname, null);
        this.externalId = StringUtils.defaultIfEmpty(externalId, null);
        this.mobileNo = StringUtils.defaultIfEmpty(mobileNo, null);
        this.loanOfficer = isLoanOfficer;
        this.active = isActive == null ? true : isActive;
        deriveDisplayName(firstname);
        this.joiningDate = joiningDate;
        // Initialize offices set with primary office if provided
        if (staffOffice != null) {
            this.offices = new HashSet<>();
            this.offices.add(staffOffice);
        }
    }

    public EnumOptionData organisationalRoleData() {
        EnumOptionData organisationalRole = null;
        if (this.organisationalRoleType != null) {
            organisationalRole = StaffEnumerations.organisationalRole(this.organisationalRoleType);
        }
        return organisationalRole;
    }

    public void changeOffice(final Office newOffice) {
        this.office = newOffice;
        // Ensure primary office is in offices set
        if (newOffice != null && !this.offices.contains(newOffice)) {
            this.offices.add(newOffice);
        }
    }

    public void setOffice(final Office office) {
        this.office = office;
        // Ensure primary office is in offices set
        if (office != null && !this.offices.contains(office)) {
            this.offices.add(office);
        }
    }

    public Set<Office> getOffices() {
        return this.offices;
    }

    public void setOffices(final Set<Office> offices) {
        this.offices = offices != null ? new HashSet<>(offices) : new HashSet<>();
        // If primary office is null but we have offices, set first office as primary
        if (this.office == null && !this.offices.isEmpty()) {
            this.office = this.offices.iterator().next();
        }
        // Ensure primary office is in the set
        if (this.office != null && !this.offices.contains(this.office)) {
            this.offices.add(this.office);
        }
    }

    public void addOffice(final Office office) {
        if (office != null) {
            this.offices.add(office);
        }
    }

    public void removeOffice(final Office office) {
        if (office != null && !office.equals(this.office)) {
            // Don't allow removing primary office
            this.offices.remove(office);
        }
    }

    public Map<String, Object> update(final JsonCommand command) {

        final Map<String, Object> actualChanges = new LinkedHashMap<>(7);

        // Handle officeIds array (multiple offices)
        final String officeIdsParamName = "officeIds";
        if (command.hasParameter(officeIdsParamName)) {
            final String[] newOfficeIdsStr = command.arrayValueOfParameterNamed(officeIdsParamName);
            final Set<Long> currentOfficeIds = new HashSet<>();
            // Ensure offices collection is initialized (trigger lazy loading if needed)
            if (this.offices != null) {
                for (Office office : this.offices) {
                    if (office != null) {
                        currentOfficeIds.add(office.getId());
                    }
                }
            }
            // If no offices found in collection, add primary office for comparison
            if (currentOfficeIds.isEmpty() && this.office != null) {
                currentOfficeIds.add(this.office.getId());
            }
            final Set<Long> newOfficeIdsSet = new HashSet<>();
            for (String officeIdStr : newOfficeIdsStr) {
                newOfficeIdsSet.add(Long.parseLong(officeIdStr));
            }
            if (!currentOfficeIds.equals(newOfficeIdsSet)) {
                actualChanges.put(officeIdsParamName, newOfficeIdsStr);
            }
        } else {
            // Backward compatibility: handle single officeId
            final String officeIdParamName = "officeId";
            if (command.isChangeInLongParameterNamed(officeIdParamName, this.office.getId())) {
                final Long newValue = command.longValueOfParameterNamed(officeIdParamName);
                actualChanges.put(officeIdParamName, newValue);
            }
        }

        boolean firstnameChanged = false;
        final String firstnameParamName = "firstname";
        if (command.isChangeInStringParameterNamed(firstnameParamName, this.firstname)) {
            final String newValue = command.stringValueOfParameterNamed(firstnameParamName);
            actualChanges.put(firstnameParamName, newValue);
            this.firstname = newValue;
            firstnameChanged = true;
        }

        boolean lastnameChanged = false;
        final String lastnameParamName = "lastname";
        if (command.isChangeInStringParameterNamed(lastnameParamName, this.lastname)) {
            final String newValue = command.stringValueOfParameterNamed(lastnameParamName);
            actualChanges.put(lastnameParamName, newValue);
            this.lastname = newValue;
            lastnameChanged = true;
        }

        if (firstnameChanged || lastnameChanged) {
            deriveDisplayName(this.firstname);
        }

        final String externalIdParamName = "externalId";
        if (command.isChangeInStringParameterNamed(externalIdParamName, this.externalId)) {
            final String newValue = command.stringValueOfParameterNamed(externalIdParamName);
            actualChanges.put(externalIdParamName, newValue);
            this.externalId = newValue;
        }

        final String mobileNoParamName = "mobileNo";
        if (command.isChangeInStringParameterNamed(mobileNoParamName, this.mobileNo)) {
            final String newValue = command.stringValueOfParameterNamed(mobileNoParamName);
            actualChanges.put(mobileNoParamName, newValue);
            this.mobileNo = StringUtils.defaultIfEmpty(newValue, null);
        }

        final String isLoanOfficerParamName = "isLoanOfficer";
        if (command.isChangeInBooleanParameterNamed(isLoanOfficerParamName, this.loanOfficer)) {
            final boolean newValue = command.booleanPrimitiveValueOfParameterNamed(isLoanOfficerParamName);
            actualChanges.put(isLoanOfficerParamName, newValue);
            this.loanOfficer = newValue;
        }

        final String isActiveParamName = "isActive";
        if (command.isChangeInBooleanParameterNamed(isActiveParamName, this.active)) {
            final boolean newValue = command.booleanPrimitiveValueOfParameterNamed(isActiveParamName);
            actualChanges.put(isActiveParamName, newValue);
            this.active = newValue;
        }

        final String joiningDateParamName = "joiningDate";
        if (command.isChangeInDateParameterNamed(joiningDateParamName, this.joiningDate)) {
            final String valueAsInput = command.stringValueOfParameterNamed(joiningDateParamName);
            actualChanges.put(joiningDateParamName, valueAsInput);
            this.joiningDate = command.localDateValueOfParameterNamed(joiningDateParamName);
        }

        return actualChanges;
    }

    public boolean isNotLoanOfficer() {
        return !isLoanOfficer();
    }

    public boolean isLoanOfficer() {
        return this.loanOfficer;
    }

    public boolean isNotActive() {
        return !isActive();
    }

    public boolean isActive() {
        return this.active;
    }

    private void deriveDisplayName(final String firstname) {
        if (!StringUtils.isBlank(firstname)) {
            this.displayName = this.lastname + ", " + this.firstname;
        } else {
            this.displayName = this.lastname;
        }
    }

    public boolean identifiedBy(final Staff staff) {
        return getId().equals(staff.getId());
    }

    public String emailAddress() {
        return emailAddress;
    }

    public Long officeId() {
        return this.office != null ? this.office.getId() : null;
    }

    public String displayName() {
        return this.displayName;
    }

    public String mobileNo() {
        return this.mobileNo;
    }

    public Office office() {
        return this.office;
    }

    public void setImage(Image image) {
        this.image = image;
    }

}
