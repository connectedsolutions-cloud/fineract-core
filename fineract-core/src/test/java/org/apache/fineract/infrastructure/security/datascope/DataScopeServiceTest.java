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
package org.apache.fineract.infrastructure.security.datascope;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Set;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

class DataScopeServiceTest {

    private PlatformSecurityContext context;
    private JdbcTemplate jdbcTemplate;
    private DataScopeService service;

    @BeforeEach
    void setUp() {
        context = mock(PlatformSecurityContext.class);
        jdbcTemplate = mock(JdbcTemplate.class);
        service = new DataScopeService(context, jdbcTemplate);
        when(jdbcTemplate.queryForObject(anyString(), eq(Integer.class), any(), any())).thenReturn(0);
    }

    @Test
    void unrestrictedWhenNoUser() {
        assertEquals(DataScope.ALL, service.effectiveScope(null));
        assertTrue(service.forClient(null, "c").isEmpty());
        assertTrue(service.canAccessLoan(99L, null, null, null, null));
    }

    @Test
    void emptyAndAllHaveNoPredicates() {
        final AppUser all = user(null, Set.of(role("ALL")), Set.of(office(1L)), 10L);
        assertEquals(DataScope.ALL, service.effectiveScope(all));
        assertTrue(service.forClient(all, "c").isEmpty());
        assertTrue(service.forLoan(all, "l", "c", "g").isEmpty());

        final AppUser emptyRole = user(null, Set.of(role(null)), Set.of(office(1L)), 10L);
        assertEquals(DataScope.ALL, service.effectiveScope(emptyRole));
        assertTrue(service.forClient(emptyRole, "c").isEmpty());
    }

    @Test
    void inheritFromWidestRole() {
        final AppUser mixed = user(null, Set.of(role("ASSIGNED"), role("ALL")), Set.of(office(1L)), 10L);
        assertEquals(DataScope.ALL, service.effectiveScope(mixed));
        assertTrue(service.forClient(mixed, "c").isEmpty());

        final AppUser officeAndAssigned = user(null, Set.of(role("ASSIGNED"), role("OFFICE")), Set.of(office(1L)), 10L);
        assertEquals(DataScope.OFFICE, service.effectiveScope(officeAndAssigned));
        when(context.getAuthenticatedUserIfPresent()).thenReturn(officeAndAssigned);
        assertTrue(service.canAccessClient(1L, 1L, 99L, 99L));
        assertFalse(service.canAccessClient(1L, 2L, 10L, 10L));
    }

    @Test
    void userOverrideWinsOverRole() {
        final AppUser looser = user("ALL", Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        assertEquals(DataScope.ALL, service.effectiveScope(looser));
        assertTrue(service.forClient(looser, "c").isEmpty());

        final AppUser tighter = user("OFFICE", Set.of(role("ALL")), Set.of(office(1L)), 10L);
        assertEquals(DataScope.OFFICE, service.effectiveScope(tighter));
        final DataScopeClause officeClause = service.forClient(tighter, "c");
        assertFalse(officeClause.isEmpty());
        assertTrue(officeClause.sql().contains("c.office_id in ("));
        assertFalse(officeClause.sql().contains("staff_id"));
    }

    @Test
    void allFunctionsImpliesAll() {
        final AppUser superUser = user("ASSIGNED", Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        when(superUser.hasAnyPermission("ALL_FUNCTIONS")).thenReturn(true);
        assertEquals(DataScope.ALL, service.effectiveScope(superUser));
        assertTrue(service.forClient(superUser, "c").isEmpty());
    }

    @Test
    void failClosedOnlyWhenRestricted() {
        final AppUser officeNoOffices = user(null, Set.of(role("OFFICE")), Set.of(), 10L);
        assertEquals(DataScopeClause.DENY.sql(), service.forClient(officeNoOffices, "c").sql());

        final AppUser assignedNoStaff = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), null);
        assertEquals(DataScopeClause.DENY.sql(), service.forClient(assignedNoStaff, "c").sql());
        when(context.getAuthenticatedUserIfPresent()).thenReturn(assignedNoStaff);
        assertFalse(service.canAccessLoan(1L, null, 10L, 10L, 10L));

        final AppUser unrestrictedNoStaff = user(null, Set.of(role("ALL")), Set.of(), null);
        assertTrue(service.forClient(unrestrictedNoStaff, "c").isEmpty());
        when(context.getAuthenticatedUserIfPresent()).thenReturn(unrestrictedNoStaff);
        assertTrue(service.canAccessLoan(99L, null, null, null, null));
    }

    @Test
    void multiOfficeInList() {
        final AppUser manager = user(null, Set.of(role("OFFICE")), Set.of(office(1L), office(2L)), 10L);
        final DataScopeClause clause = service.forClient(manager, "c");
        assertEquals(List.of(1L, 2L), sortedLongs(clause.params()));
        assertTrue(clause.sql().contains("c.office_id in ("));
        when(context.getAuthenticatedUserIfPresent()).thenReturn(manager);
        assertTrue(service.canAccessClient(10L, 1L, null, null));
        assertTrue(service.canAccessClient(10L, 2L, null, null));
        assertFalse(service.canAccessClient(10L, 3L, null, null));
    }

    @Test
    void loanAssignedOrOfficerGestorOrStaff() {
        final AppUser ana = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        when(context.getAuthenticatedUserIfPresent()).thenReturn(ana);

        assertTrue(service.canAccessLoan(1L, null, 10L, 99L, 99L));
        assertTrue(service.canAccessLoan(1L, null, 99L, 99L, 10L));
        assertTrue(service.canAccessLoan(1L, null, 99L, 10L, 99L));
        assertFalse(service.canAccessLoan(1L, null, 99L, 99L, 99L));
        assertFalse(service.canAccessLoan(2L, null, 10L, 10L, 10L));
        assertTrue(service.canAccessLoan(null, 1L, 10L, null, null));
    }

    @Test
    void assignedNeverMatchesNullAssignment() {
        final AppUser ana = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        when(context.getAuthenticatedUserIfPresent()).thenReturn(ana);
        assertFalse(service.canAccessLoan(1L, null, null, null, null));
        assertFalse(service.canAccessSavings(1L, null, null, null));
        assertFalse(service.canAccessShare(1L, null, null));
        assertFalse(service.canAccessClient(5L, 1L, null, null));
    }

    @Test
    void clientAssignedAllowsProductOnlyOfficer() {
        final AppUser ana = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        when(context.getAuthenticatedUserIfPresent()).thenReturn(ana);
        when(jdbcTemplate.queryForObject(anyString(), eq(Integer.class), eq(5L), eq(10L))).thenReturn(1);
        assertTrue(service.canAccessClient(5L, 1L, 99L, 99L));
    }

    @Test
    void loanSqlIncludesStaffOrGestor() {
        final AppUser ana = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        final DataScopeClause clause = service.forLoan(ana, "l", "c", "g");
        assertTrue(clause.sql().contains("l.loan_officer_id = ?"));
        assertTrue(clause.sql().contains("c.gestor_id = ?"));
        assertTrue(clause.sql().contains("c.staff_id = ?"));
        assertTrue(clause.sql().contains("credesal_client_staff_assignment"));
        assertTrue(clause.sql().contains("credesal_loan_staff_assignment"));
        assertTrue(clause.params().contains(10L));
        assertFalse(clause.sql().contains("hierarchy"));
    }

    @Test
    void loanRoleAssignmentGrantsOnlyTheLoan() {
        final AppUser ana = user(null, Set.of(role("ASSIGNED")), Set.of(office(1L)), 10L);
        when(context.getAuthenticatedUserIfPresent()).thenReturn(ana);
        when(jdbcTemplate.queryForObject(anyString(), eq(Integer.class), eq(101L), eq(10L), eq(10L), eq(10L))).thenReturn(1);

        assertTrue(service.canAccessLoan(101L, 5L, 1L, null, null, null, null));
        assertFalse(service.canAccessLoan(102L, 5L, 1L, null, null, null, null));
        assertFalse(service.canAccessSavings(1L, null, null, null));
        assertFalse(service.canAccessShare(1L, null, null));
    }

    private static List<Long> sortedLongs(final List<Object> params) {
        return params.stream().map(value -> (Long) value).sorted().toList();
    }

    private static AppUser user(final String override, final Set<Role> roles, final Set<Office> offices, final Long staffId) {
        final AppUser user = mock(AppUser.class);
        when(user.getDataScope()).thenReturn(override);
        when(user.getRoles()).thenReturn(roles);
        when(user.getOffices()).thenReturn(offices);
        when(user.getStaffId()).thenReturn(staffId);
        when(user.hasAnyPermission("ALL_FUNCTIONS")).thenReturn(false);
        return user;
    }

    private static Role role(final String dataScope) {
        final Role role = mock(Role.class);
        when(role.getDataScope()).thenReturn(dataScope);
        return role;
    }

    private static Office office(final Long id) {
        final Office office = mock(Office.class);
        when(office.getId()).thenReturn(id);
        return office;
    }
}
