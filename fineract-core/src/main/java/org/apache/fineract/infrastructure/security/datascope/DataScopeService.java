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

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.Role;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class DataScopeService {

    public static final String NAMED_OFFICE_IDS = "dsOfficeIds";
    public static final String NAMED_STAFF_ID = "dsStaffId";

    private final PlatformSecurityContext context;
    private final JdbcTemplate jdbcTemplate;

    public DataScope effectiveScope() {
        return effectiveScope(currentUserOrNull());
    }

    public DataScope effectiveScope(final AppUser user) {
        if (user == null) {
            return DataScope.ALL;
        }
        if (user.hasAnyPermission("ALL_FUNCTIONS")) {
            return DataScope.ALL;
        }
        final DataScope override = DataScope.fromUserOverride(user.getDataScope());
        if (override != null) {
            return override;
        }
        DataScope widest = null;
        if (user.getRoles() != null) {
            for (final Role role : user.getRoles()) {
                final DataScope roleScope = DataScope.fromRoleValue(role.getDataScope());
                if (widest == null || roleScope.isWiderThan(widest)) {
                    widest = roleScope;
                }
            }
        }
        return widest == null ? DataScope.ALL : widest;
    }

    public Set<Long> officeIds(final AppUser user) {
        final Set<Long> ids = new HashSet<>();
        if (user == null || user.getOffices() == null) {
            return ids;
        }
        for (final Office office : user.getOffices()) {
            if (office != null && office.getId() != null) {
                ids.add(office.getId());
            }
        }
        return ids;
    }

    public Long staffId(final AppUser user) {
        return user == null ? null : user.getStaffId();
    }

    public DataScopeClause forClient(final String clientAlias) {
        return forClient(currentUserOrNull(), clientAlias);
    }

    public DataScopeClause forClient(final AppUser user, final String clientAlias) {
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return DataScopeClause.NONE;
        }
        final Set<Long> offices = officeIds(user);
        if (offices.isEmpty()) {
            return DataScopeClause.DENY;
        }
        final List<Object> params = new ArrayList<>();
        final StringBuilder sql = new StringBuilder();
        sql.append(" and ").append(in(clientAlias + ".office_id", offices, params)).append(" ");
        if (scope == DataScope.ASSIGNED) {
            final Long staffId = staffId(user);
            if (staffId == null) {
                return DataScopeClause.DENY;
            }
            sql.append(" and (").append(clientAlias).append(".staff_id = ? or ").append(clientAlias).append(".gestor_id = ?");
            params.add(staffId);
            params.add(staffId);
            sql.append(" or exists (select 1 from m_loan lx where lx.client_id = ").append(clientAlias)
                    .append(".id and lx.loan_officer_id = ?)");
            params.add(staffId);
            sql.append(" or exists (select 1 from credesal_client_staff_assignment ca where ca.client_id = ").append(clientAlias)
                    .append(".id and (ca.promoter_staff_id = ? or ca.account_executive_staff_id = ? or ca.collections_manager_staff_id = ?))");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
            sql.append(" or exists (select 1 from credesal_loan_staff_assignment la where la.client_id = ").append(clientAlias)
                    .append(".id and (la.promoter_staff_id = ? or la.account_executive_staff_id = ? or la.collections_manager_staff_id = ?))");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
            sql.append(" or exists (select 1 from m_savings_account sx where sx.client_id = ").append(clientAlias)
                    .append(".id and sx.field_officer_id = ?)) ");
            params.add(staffId);
        }
        return new DataScopeClause(sql.toString(), params);
    }

    public DataScopeClause forLoan(final String loanAlias, final String clientAlias, final String groupAlias) {
        return forLoan(currentUserOrNull(), loanAlias, clientAlias, groupAlias);
    }

    public DataScopeClause forLoan(final AppUser user, final String loanAlias, final String clientAlias, final String groupAlias) {
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return DataScopeClause.NONE;
        }
        final Set<Long> offices = officeIds(user);
        if (offices.isEmpty()) {
            return DataScopeClause.DENY;
        }
        final List<Object> params = new ArrayList<>();
        final StringBuilder sql = new StringBuilder();
        sql.append(" and (").append(in(clientAlias + ".office_id", offices, params));
        sql.append(" or ").append(in(groupAlias + ".office_id", offices, params)).append(") ");
        if (scope == DataScope.ASSIGNED) {
            final Long staffId = staffId(user);
            if (staffId == null) {
                return DataScopeClause.DENY;
            }
            sql.append(" and (").append(loanAlias).append(".loan_officer_id = ? or ").append(clientAlias).append(".gestor_id = ? or ")
                    .append(clientAlias).append(".staff_id = ?");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
            sql.append(" or exists (select 1 from credesal_client_staff_assignment ca where ca.client_id = ").append(clientAlias)
                    .append(".id and (ca.promoter_staff_id = ? or ca.account_executive_staff_id = ? or ca.collections_manager_staff_id = ?))");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
            sql.append(" or exists (select 1 from credesal_loan_staff_assignment la where la.loan_id = ").append(loanAlias)
                    .append(".id and (la.promoter_staff_id = ? or la.account_executive_staff_id = ? or la.collections_manager_staff_id = ?))) ");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
        }
        return new DataScopeClause(sql.toString(), params);
    }

    public DataScopeClause forSavings(final String savingsAlias, final String clientAlias) {
        return forSavings(currentUserOrNull(), savingsAlias, clientAlias);
    }

    public DataScopeClause forSavings(final AppUser user, final String savingsAlias, final String clientAlias) {
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return DataScopeClause.NONE;
        }
        final Set<Long> offices = officeIds(user);
        if (offices.isEmpty()) {
            return DataScopeClause.DENY;
        }
        final List<Object> params = new ArrayList<>();
        final StringBuilder sql = new StringBuilder();
        sql.append(" and ").append(in(clientAlias + ".office_id", offices, params)).append(" ");
        if (scope == DataScope.ASSIGNED) {
            final Long staffId = staffId(user);
            if (staffId == null) {
                return DataScopeClause.DENY;
            }
            sql.append(" and (").append(savingsAlias).append(".field_officer_id = ? or ").append(clientAlias).append(".gestor_id = ? or ")
                    .append(clientAlias).append(".staff_id = ?) ");
            params.add(staffId);
            params.add(staffId);
            params.add(staffId);
        }
        return new DataScopeClause(sql.toString(), params);
    }

    public DataScopeClause forShare(final String clientAlias) {
        return forShare(currentUserOrNull(), clientAlias);
    }

    public DataScopeClause forShare(final AppUser user, final String clientAlias) {
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return DataScopeClause.NONE;
        }
        final Set<Long> offices = officeIds(user);
        if (offices.isEmpty()) {
            return DataScopeClause.DENY;
        }
        final List<Object> params = new ArrayList<>();
        final StringBuilder sql = new StringBuilder();
        sql.append(" and ").append(in(clientAlias + ".office_id", offices, params)).append(" ");
        if (scope == DataScope.ASSIGNED) {
            final Long staffId = staffId(user);
            if (staffId == null) {
                return DataScopeClause.DENY;
            }
            sql.append(" and (").append(clientAlias).append(".staff_id = ? or ").append(clientAlias).append(".gestor_id = ?) ");
            params.add(staffId);
            params.add(staffId);
        }
        return new DataScopeClause(sql.toString(), params);
    }

    /**
     * Named-parameter SQL fragment for search unions. Empty string when unrestricted.
     */
    public String namedSqlForClient(final String clientAlias) {
        return namedOfficeAndAssigned(clientAlias, null, "client");
    }

    public String namedSqlForLoan(final String loanAlias, final String clientAlias) {
        return namedOfficeAndAssigned(clientAlias, loanAlias, "loan");
    }

    public String namedSqlForSavings(final String savingsAlias, final String clientAlias) {
        return namedOfficeAndAssigned(clientAlias, savingsAlias, "savings");
    }

    public String namedSqlForShare(final String clientAlias) {
        return namedOfficeAndAssigned(clientAlias, null, "share");
    }

    public String namedSqlForOfficeOnly(final String officeIdColumn) {
        final DataScope scope = effectiveScope();
        if (scope.isUnrestricted()) {
            return "";
        }
        return " and " + officeIdColumn + " in (:" + NAMED_OFFICE_IDS + ") ";
    }

    public void bindNamedParams(final MapSqlParameterSource params) {
        final AppUser user = currentUserOrNull();
        final Set<Long> offices = officeIds(user);
        params.addValue(NAMED_OFFICE_IDS, offices.isEmpty() ? List.of(-1L) : new ArrayList<>(offices));
        final Long staffId = staffId(user);
        params.addValue(NAMED_STAFF_ID, staffId == null ? -1L : staffId);
    }

    public boolean canAccessClient(final Client client) {
        if (client == null) {
            return false;
        }
        final Long officeId = client.getOffice() == null ? null : client.getOffice().getId();
        return canAccessClient(client.getId(), officeId, client.staffId(), client.gestorId());
    }

    public boolean canAccessClient(final Long clientId, final Long officeId, final Long clientStaffId, final Long gestorId) {
        final AppUser user = currentUserOrNull();
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return true;
        }
        final Set<Long> offices = officeIds(user);
        if (officeId == null || !offices.contains(officeId)) {
            return false;
        }
        if (scope == DataScope.OFFICE) {
            return true;
        }
        final Long staffId = staffId(user);
        if (staffId == null) {
            return false;
        }
        if (staffId.equals(clientStaffId) || staffId.equals(gestorId)) {
            return true;
        }
        return clientId != null && hasAssignedProduct(clientId, staffId);
    }

    public boolean canAccessLoan(final Long officeId, final Long groupOfficeId, final Long loanOfficerId, final Long clientStaffId,
            final Long gestorId) {
        return canAccessLoan(null, null, officeId, groupOfficeId, loanOfficerId, clientStaffId, gestorId);
    }

    public boolean canAccessLoan(final Long loanId, final Long clientId, final Long officeId, final Long groupOfficeId,
            final Long loanOfficerId, final Long clientStaffId, final Long gestorId) {
        final AppUser user = currentUserOrNull();
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return true;
        }
        final Set<Long> offices = officeIds(user);
        final boolean inOffice = (officeId != null && offices.contains(officeId))
                || (groupOfficeId != null && offices.contains(groupOfficeId));
        if (!inOffice) {
            return false;
        }
        if (scope == DataScope.OFFICE) {
            return true;
        }
        final Long staffId = staffId(user);
        if (staffId == null) {
            return false;
        }
        if (staffId.equals(loanOfficerId) || staffId.equals(gestorId) || staffId.equals(clientStaffId)) {
            return true;
        }
        return hasClientStaffAssignment(clientId, staffId) || hasLoanStaffAssignment(loanId, staffId);
    }

    public boolean canAccessSavings(final Long officeId, final Long fieldOfficerId, final Long clientStaffId, final Long gestorId) {
        final AppUser user = currentUserOrNull();
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return true;
        }
        final Set<Long> offices = officeIds(user);
        if (officeId == null || !offices.contains(officeId)) {
            return false;
        }
        if (scope == DataScope.OFFICE) {
            return true;
        }
        final Long staffId = staffId(user);
        if (staffId == null) {
            return false;
        }
        return staffId.equals(fieldOfficerId) || staffId.equals(gestorId) || staffId.equals(clientStaffId);
    }

    public boolean canAccessShare(final Long officeId, final Long clientStaffId, final Long gestorId) {
        final AppUser user = currentUserOrNull();
        final DataScope scope = effectiveScope(user);
        if (scope.isUnrestricted()) {
            return true;
        }
        final Set<Long> offices = officeIds(user);
        if (officeId == null || !offices.contains(officeId)) {
            return false;
        }
        if (scope == DataScope.OFFICE) {
            return true;
        }
        final Long staffId = staffId(user);
        if (staffId == null) {
            return false;
        }
        return staffId.equals(clientStaffId) || staffId.equals(gestorId);
    }

    private String namedOfficeAndAssigned(final String clientAlias, final String productAlias, final String kind) {
        final DataScope scope = effectiveScope();
        if (scope.isUnrestricted()) {
            return "";
        }
        final StringBuilder sql = new StringBuilder();
        if ("loan".equals(kind) || "savings".equals(kind)) {
            sql.append(" and (").append(clientAlias).append(".office_id in (:").append(NAMED_OFFICE_IDS).append(") or g.office_id in (:")
                    .append(NAMED_OFFICE_IDS).append(")) ");
        } else {
            sql.append(" and ").append(clientAlias).append(".office_id in (:").append(NAMED_OFFICE_IDS).append(") ");
        }
        if (scope == DataScope.ASSIGNED) {
            if ("loan".equals(kind)) {
                sql.append(" and (").append(productAlias).append(".loan_officer_id = :").append(NAMED_STAFF_ID).append(" or ")
                        .append(clientAlias).append(".gestor_id = :").append(NAMED_STAFF_ID).append(" or ").append(clientAlias)
                        .append(".staff_id = :").append(NAMED_STAFF_ID);
                appendNamedClientStaffAssignment(sql, clientAlias);
                sql.append(" or exists (select 1 from credesal_loan_staff_assignment la where la.loan_id = ").append(productAlias)
                        .append(".id and (la.promoter_staff_id = :").append(NAMED_STAFF_ID)
                        .append(" or la.account_executive_staff_id = :").append(NAMED_STAFF_ID)
                        .append(" or la.collections_manager_staff_id = :").append(NAMED_STAFF_ID).append("))) ");
            } else if ("savings".equals(kind)) {
                sql.append(" and (").append(productAlias).append(".field_officer_id = :").append(NAMED_STAFF_ID).append(" or ")
                        .append(clientAlias).append(".gestor_id = :").append(NAMED_STAFF_ID).append(" or ").append(clientAlias)
                        .append(".staff_id = :").append(NAMED_STAFF_ID).append(") ");
            } else if ("share".equals(kind) || "client".equals(kind)) {
                sql.append(" and (").append(clientAlias).append(".staff_id = :").append(NAMED_STAFF_ID).append(" or ").append(clientAlias)
                        .append(".gestor_id = :").append(NAMED_STAFF_ID);
                if ("client".equals(kind)) {
                    sql.append(" or exists (select 1 from m_loan lx where lx.client_id = ").append(clientAlias)
                            .append(".id and lx.loan_officer_id = :").append(NAMED_STAFF_ID).append(")");
                    appendNamedClientStaffAssignment(sql, clientAlias);
                    sql.append(" or exists (select 1 from credesal_loan_staff_assignment la where la.client_id = ").append(clientAlias)
                            .append(".id and (la.promoter_staff_id = :").append(NAMED_STAFF_ID)
                            .append(" or la.account_executive_staff_id = :").append(NAMED_STAFF_ID)
                            .append(" or la.collections_manager_staff_id = :").append(NAMED_STAFF_ID).append("))");
                    sql.append(" or exists (select 1 from m_savings_account sx where sx.client_id = ").append(clientAlias)
                            .append(".id and sx.field_officer_id = :").append(NAMED_STAFF_ID).append(")");
                }
                sql.append(") ");
            }
        }
        return sql.toString();
    }

    private boolean hasAssignedProduct(final Long clientId, final Long staffId) {
        if (hasClientStaffAssignment(clientId, staffId)) {
            return true;
        }
        final Integer loanHit = jdbcTemplate.queryForObject(
                "select case when exists (select 1 from m_loan l left join credesal_loan_staff_assignment a on a.loan_id=l.id "
                        + "where l.client_id = ? and (l.loan_officer_id = ? or a.promoter_staff_id = ? "
                        + "or a.account_executive_staff_id = ? or a.collections_manager_staff_id = ?)) then 1 else 0 end",
                Integer.class, clientId, staffId, staffId, staffId, staffId);
        if (loanHit != null && loanHit == 1) {
            return true;
        }
        final Integer savingsHit = jdbcTemplate.queryForObject(
                "select case when exists (select 1 from m_savings_account where client_id = ? and field_officer_id = ?) then 1 else 0 end",
                Integer.class, clientId, staffId);
        return savingsHit != null && savingsHit == 1;
    }

    private void appendNamedClientStaffAssignment(final StringBuilder sql, final String clientAlias) {
        sql.append(" or exists (select 1 from credesal_client_staff_assignment ca where ca.client_id = ").append(clientAlias)
                .append(".id and (ca.promoter_staff_id = :").append(NAMED_STAFF_ID)
                .append(" or ca.account_executive_staff_id = :").append(NAMED_STAFF_ID)
                .append(" or ca.collections_manager_staff_id = :").append(NAMED_STAFF_ID).append("))");
    }

    private boolean hasClientStaffAssignment(final Long clientId, final Long staffId) {
        if (clientId == null) {
            return false;
        }
        final Integer hit = jdbcTemplate.queryForObject(
                "select case when exists (select 1 from credesal_client_staff_assignment where client_id = ? "
                        + "and (promoter_staff_id = ? or account_executive_staff_id = ? or collections_manager_staff_id = ?)) "
                        + "then 1 else 0 end",
                Integer.class, clientId, staffId, staffId, staffId);
        return hit != null && hit == 1;
    }

    private boolean hasLoanStaffAssignment(final Long loanId, final Long staffId) {
        if (loanId == null) {
            return false;
        }
        final Integer hit = jdbcTemplate.queryForObject(
                "select case when exists (select 1 from credesal_loan_staff_assignment where loan_id = ? "
                        + "and (promoter_staff_id = ? or account_executive_staff_id = ? or collections_manager_staff_id = ?)) "
                        + "then 1 else 0 end",
                Integer.class, loanId, staffId, staffId, staffId);
        return hit != null && hit == 1;
    }

    private String in(final String column, final Set<Long> ids, final List<Object> params) {
        final StringBuilder sql = new StringBuilder(column).append(" in (");
        boolean first = true;
        for (final Long id : ids) {
            if (!first) {
                sql.append(',');
            }
            sql.append('?');
            params.add(id);
            first = false;
        }
        sql.append(')');
        return sql.toString();
    }

    private AppUser currentUserOrNull() {
        return this.context.getAuthenticatedUserIfPresent();
    }
}
