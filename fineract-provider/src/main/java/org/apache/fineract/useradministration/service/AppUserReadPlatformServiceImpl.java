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
package org.apache.fineract.useradministration.service;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.domain.JdbcSupport;
import org.apache.fineract.infrastructure.security.datascope.DataScopeService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.data.OfficeData;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.service.OfficeReadPlatformService;
import org.apache.fineract.organisation.staff.data.StaffData;
import org.apache.fineract.organisation.staff.service.StaffReadPlatformService;
import org.apache.fineract.portfolio.client.data.ClientData;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.useradministration.data.AppUserData;
import org.apache.fineract.useradministration.data.RoleData;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserClientMapping;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.apache.fineract.useradministration.domain.Role;
import org.apache.fineract.useradministration.exception.UserNotFoundException;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

@RequiredArgsConstructor
public class AppUserReadPlatformServiceImpl implements AppUserReadPlatformService {

    private final PlatformSecurityContext context;
    private final JdbcTemplate jdbcTemplate;
    private final OfficeReadPlatformService officeReadPlatformService;
    private final RoleReadPlatformService roleReadPlatformService;
    private final AppUserRepository appUserRepository;
    private final StaffReadPlatformService staffReadPlatformService;
    private final DataScopeService dataScopeService;

    /*
     * used for caching in spring expression language.
     */
    public PlatformSecurityContext getContext() {
        return this.context;
    }

    @Override
    @Cacheable(value = "users", key = "T(org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil).getTenant().getTenantIdentifier().concat(#root.target.context.authenticatedUser().getOffice().getHierarchy())")
    public Collection<AppUserData> retrieveAllUsers() {

        final AppUser currentUser = this.context.authenticatedUser();
        final String hierarchy = currentUser.getOffice().getHierarchy();
        final String hierarchySearchString = hierarchy + "%";

        final AppUserMapper mapper = new AppUserMapper(this.roleReadPlatformService, this.staffReadPlatformService);
        final String sql = "select " + mapper.schema();

        return this.jdbcTemplate.query(sql, mapper, new Object[] { hierarchySearchString }); // NOSONAR
    }

    @Override
    public Collection<AppUserData> retrieveSearchTemplate() {
        final AppUser currentUser = this.context.authenticatedUser();
        final String hierarchy = currentUser.getOffice().getHierarchy();
        final String hierarchySearchString = hierarchy + "%";

        final AppUserLookupMapper mapper = new AppUserLookupMapper();
        final String sql = "select " + mapper.schema();

        return this.jdbcTemplate.query(sql, mapper, new Object[] { hierarchySearchString }); // NOSONAR
    }

    @Override
    public AppUserData retrieveNewUserDetails() {

        final Collection<OfficeData> offices = this.officeReadPlatformService.retrieveAllOfficesForDropdown();
        final Collection<RoleData> availableRoles = this.roleReadPlatformService.retrieveAllActiveRoles();
        final Collection<RoleData> selfServiceRoles = this.roleReadPlatformService.retrieveAllSelfServiceRoles();

        return AppUserData.template(offices, availableRoles, selfServiceRoles);
    }

    @Override
    public AppUserData retrieveUser(final Long userId) {

        this.context.authenticatedUser();

        final AppUser user = this.appUserRepository.findById(userId).orElseThrow(() -> new UserNotFoundException(userId));
        if (user.isDeleted()) {
            throw new UserNotFoundException(userId);
        }

        final Collection<RoleData> availableRoles = this.roleReadPlatformService.retrieveAll();

        final Collection<RoleData> selectedUserRoles = new ArrayList<>();
        final Set<Role> userRoles = user.getRoles();
        for (final Role role : userRoles) {
            selectedUserRoles.add(role.toData());
        }

        availableRoles.removeAll(selectedUserRoles);

        final StaffData linkedStaff;
        if (user.getStaff() != null) {
            linkedStaff = this.staffReadPlatformService.retrieveStaff(user.getStaffId());
        } else {
            linkedStaff = null;
        }

        // Collect all office IDs
        final List<Long> officeIds = new ArrayList<>();
        for (final Office office : user.getOffices()) {
            officeIds.add(office.getId());
        }

        // Get allowed offices for dropdown (needed for frontend to display office names)
        final Collection<OfficeData> allowedOffices = this.officeReadPlatformService.retrieveAllOfficesForDropdown();

        AppUserData retUser = AppUserData.instance(user.getId(), user.getUsername(), user.getEmail(), user.getCurrentOffice().getId(),
                user.getCurrentOffice().getName(), user.getCurrentOffice().getId(), officeIds, user.getFirstname(), user.getLastname(),
                availableRoles, null, selectedUserRoles, linkedStaff, user.getPasswordNeverExpires(), user.isSelfServiceUser());

        // Set allowed offices for frontend
        retUser = AppUserData.template(retUser, allowedOffices);
        retUser.setDataScope(user.getDataScope());
        retUser.setEffectiveDataScope(this.dataScopeService.effectiveScope(user).name());

        if (retUser.isSelfServiceUser()) {
            Set<ClientData> clients = new HashSet<>();
            for (AppUserClientMapping clientMap : user.getAppUserClientMappings()) {
                Client client = clientMap.getClient();
                clients.add(ClientData.lookup(client.getId(), client.getDisplayName(), client.getOffice().getId(),
                        client.getOffice().getName()));
            }
            retUser.setClients(clients);
        }

        return retUser;
    }

    private static final class AppUserMapper implements RowMapper<AppUserData> {

        private final RoleReadPlatformService roleReadPlatformService;
        private final StaffReadPlatformService staffReadPlatformService;

        AppUserMapper(final RoleReadPlatformService roleReadPlatformService, final StaffReadPlatformService staffReadPlatformService) {
            this.roleReadPlatformService = roleReadPlatformService;
            this.staffReadPlatformService = staffReadPlatformService;
        }

        @Override
        public AppUserData mapRow(final ResultSet rs, @SuppressWarnings("unused") final int rowNum) throws SQLException {

            final Long id = rs.getLong("id");
            final String username = rs.getString("username");
            final String firstname = rs.getString("firstname");
            final String lastname = rs.getString("lastname");
            final String email = rs.getString("email");
            final Long officeId = JdbcSupport.getLong(rs, "officeId");
            final String officeName = rs.getString("officeName");
            final Long currentOfficeId = JdbcSupport.getLong(rs, "currentOfficeId");
            final Long staffId = JdbcSupport.getLong(rs, "staffId");
            final Boolean passwordNeverExpire = rs.getBoolean("passwordNeverExpires");
            final Boolean isSelfServiceUser = rs.getBoolean("isSelfServiceUser");
            final Collection<RoleData> selectedRoles = this.roleReadPlatformService.retrieveAppUserRoles(id);

            final StaffData linkedStaff;
            if (staffId != null) {
                linkedStaff = this.staffReadPlatformService.retrieveStaff(staffId);
            } else {
                linkedStaff = null;
            }
            // Offices list is not available in this mapper, will be null for list queries
            return AppUserData.instance(id, username, email, officeId, officeName, currentOfficeId != null ? currentOfficeId : officeId,
                    null, firstname, lastname, null, null, selectedRoles, linkedStaff, passwordNeverExpire, isSelfServiceUser);
        }

        public String schema() {
            return " u.id as id, u.username as username, u.firstname as firstname, u.lastname as lastname, u.email as email, u.password_never_expires as passwordNeverExpires, "
                    + " u.current_office_id as officeId, o.name as officeName, u.current_office_id as currentOfficeId, u.staff_id as staffId, u.is_self_service_user as isSelfServiceUser from m_appuser u "
                    + " join m_office o on o.id = u.current_office_id where o.hierarchy like ? and u.is_deleted=false order by u.username";
        }

    }

    private static final class AppUserLookupMapper implements RowMapper<AppUserData> {

        @Override
        public AppUserData mapRow(final ResultSet rs, @SuppressWarnings("unused") final int rowNum) throws SQLException {

            final Long id = rs.getLong("id");
            final String username = rs.getString("username");

            return AppUserData.dropdown(id, username);
        }

        public String schema() {
            return " u.id as id, u.username as username from m_appuser u "
                    + " join m_office o on o.id = u.office_id where o.hierarchy like ? and u.is_deleted=false order by u.username";
        }
    }

    @Override
    public boolean isUsernameExist(String username) {
        String sql = "select count(*) from m_appuser where username = ?";
        Object[] params = new Object[] { username };
        int count = this.jdbcTemplate.queryForObject(sql, Integer.class, params);
        return count != 0;
    }
}
