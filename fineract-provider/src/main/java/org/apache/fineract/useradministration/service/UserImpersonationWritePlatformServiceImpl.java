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

import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.data.AuthenticatedUserData;
import org.apache.fineract.infrastructure.security.datascope.DataScopeService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.infrastructure.security.service.UserImpersonationConstants;
import org.apache.fineract.infrastructure.security.service.UserImpersonationContext;
import org.apache.fineract.useradministration.data.RoleData;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.apache.fineract.useradministration.domain.Role;
import org.apache.fineract.useradministration.exception.UserNotFoundException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class UserImpersonationWritePlatformServiceImpl implements UserImpersonationWritePlatformService {

    private final PlatformSecurityContext context;
    private final AppUserRepository appUserRepository;
    private final JdbcTemplate jdbcTemplate;
    private final DataScopeService dataScopeService;

    @Override
    @Transactional
    public AuthenticatedUserData loginAs(final Long targetUserId) {
        if (UserImpersonationContext.isActive()) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.nested.not.allowed",
                    "Already impersonating another user.");
        }
        final AppUser actor = resolveActor();
        actor.validateHasPermissionTo(UserImpersonationConstants.PERMISSION);
        final AppUser target = validateTarget(actor, targetUserId);
        writeStartLog(actor.getId(), target.getId());
        return toAuthenticatedUserData(target);
    }

    @Override
    @Transactional
    public void stopLoginAs(final Long targetUserId) {
        final AppUser actor = resolveActor();
        actor.validateHasPermissionTo(UserImpersonationConstants.PERMISSION);
        if (targetUserId == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.target.required",
                    "Target user is required to stop impersonation.");
        }
        closeOpenLogs(actor.getId(), targetUserId);
    }

    @Override
    @Transactional(readOnly = true)
    public AppUser loadTargetUserForImpersonation(final Long targetUserId) {
        final AppUser actor = resolveActor();
        actor.validateHasPermissionTo(UserImpersonationConstants.PERMISSION);
        final AppUser target = validateTarget(actor, targetUserId);
        target.getAuthorities();
        if (target.getOffice() != null) {
            target.getOffice().getName();
        }
        return target;
    }

    private AppUser resolveActor() {
        if (UserImpersonationContext.isActive()) {
            return UserImpersonationContext.getOriginalUser();
        }
        return this.context.authenticatedUser();
    }

    private AppUser validateTarget(final AppUser actor, final Long targetUserId) {
        if (targetUserId == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.target.required", "Target user is required.");
        }
        if (actor.getId().equals(targetUserId)) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.self.not.allowed", "You cannot log in as yourself.");
        }
        final AppUser target = this.appUserRepository.findById(targetUserId).orElseThrow(() -> new UserNotFoundException(targetUserId));
        if (target.isDeleted() || !target.isEnabled()) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.target.inactive",
                    "Cannot log in as a deleted or disabled user.", targetUserId);
        }
        if (AppUserConstants.SYSTEM_USER_NAME.equalsIgnoreCase(target.getUsername())) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.system.user.not.allowed",
                    "Cannot log in as the system user.");
        }
        if (target.hasAnyPermission("ALL_FUNCTIONS") && !actor.hasAnyPermission("ALL_FUNCTIONS")) {
            throw new GeneralPlatformDomainRuleException("error.msg.user.impersonation.privilege.escalation",
                    "Cannot log in as a Super User unless you are also a Super User.");
        }
        return target;
    }

    private AuthenticatedUserData toAuthenticatedUserData(final AppUser target) {
        final Collection<String> permissions = new ArrayList<>();
        for (final GrantedAuthority authority : target.getAuthorities()) {
            permissions.add(authority.getAuthority());
        }
        final Collection<RoleData> roles = new ArrayList<>();
        final Set<Role> userRoles = target.getRoles();
        if (userRoles != null) {
            for (final Role role : userRoles) {
                roles.add(role.toData());
            }
        }
        final Long officeId = target.getOffice() != null ? target.getOffice().getId() : null;
        final String officeName = target.getOffice() != null ? target.getOffice().getName() : null;
        final EnumOptionData organisationalRole = target.organisationalRoleData();
        return new AuthenticatedUserData().setUsername(target.getUsername()).setUserId(target.getId()).setAuthenticated(true)
                .setOfficeId(officeId).setOfficeName(officeName).setStaffId(target.getStaffId())
                .setStaffDisplayName(target.getStaffDisplayName()).setOrganisationalRole(organisationalRole).setRoles(roles)
                .setPermissions(permissions).setShouldRenewPassword(false).setTwoFactorAuthenticationRequired(false)
                .setDataScope(this.dataScopeService.effectiveScope(target).name()).setDataScopeOverride(target.getDataScope());
    }

    private void writeStartLog(final Long actorId, final Long targetId) {
        this.jdbcTemplate.update("INSERT INTO m_user_impersonation_log (actor_id, target_id, started_on_utc) VALUES (?, ?, ?)", actorId,
                targetId, Timestamp.from(DateUtils.getAuditOffsetDateTime().toInstant()));
    }

    private void closeOpenLogs(final Long actorId, final Long targetId) {
        this.jdbcTemplate.update(
                "UPDATE m_user_impersonation_log SET ended_on_utc = ? WHERE actor_id = ? AND target_id = ? AND ended_on_utc IS NULL",
                Timestamp.from(DateUtils.getAuditOffsetDateTime().toInstant()), actorId, targetId);
    }
}
