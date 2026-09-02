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
package org.apache.fineract.infrastructure.security.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.AbstractPlatformException;
import org.apache.fineract.infrastructure.security.exception.NoAuthorizationException;
import org.apache.fineract.infrastructure.security.service.UserImpersonationConstants;
import org.apache.fineract.infrastructure.security.service.UserImpersonationContext;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.service.UserImpersonationWritePlatformService;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * After basic auth, swaps the effective principal to the target user when the impersonation header is present.
 */
@RequiredArgsConstructor
public class UserImpersonationFilter extends OncePerRequestFilter {

    private final UserImpersonationWritePlatformService userImpersonationWritePlatformService;

    @Override
    protected void doFilterInternal(final HttpServletRequest request, final HttpServletResponse response, final FilterChain filterChain)
            throws ServletException, IOException {
        final String headerValue = request.getHeader(UserImpersonationConstants.HEADER);
        final String command = request.getParameter("command");
        if (UserImpersonationConstants.COMMAND_LOGIN_AS.equalsIgnoreCase(command) && StringUtils.isNotBlank(headerValue)) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN, "Already impersonating another user.");
            return;
        }
        if (StringUtils.isBlank(headerValue) || shouldSkip(request)) {
            filterChain.doFilter(request, response);
            return;
        }
        try {
            final Long targetUserId = Long.valueOf(headerValue.trim());
            final Authentication current = SecurityContextHolder.getContext().getAuthentication();
            if (current == null || !(current.getPrincipal() instanceof AppUser actor)) {
                filterChain.doFilter(request, response);
                return;
            }
            final AppUser target = this.userImpersonationWritePlatformService.loadTargetUserForImpersonation(targetUserId);
            UserImpersonationContext.setOriginalUser(actor);
            final UsernamePasswordAuthenticationToken impersonated = new UsernamePasswordAuthenticationToken(target,
                    current.getCredentials(), target.getAuthorities());
            impersonated.setDetails(current.getDetails());
            SecurityContextHolder.getContext().setAuthentication(impersonated);
            filterChain.doFilter(request, response);
        } catch (final NumberFormatException ex) {
            response.sendError(HttpServletResponse.SC_BAD_REQUEST, "Invalid impersonation user id");
        } catch (final AbstractPlatformException ex) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN, ex.getDefaultUserMessage());
        } catch (final NoAuthorizationException ex) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN, ex.getMessage());
        } finally {
            UserImpersonationContext.clear();
        }
    }

    private boolean shouldSkip(final HttpServletRequest request) {
        final String command = request.getParameter("command");
        return UserImpersonationConstants.COMMAND_LOGIN_AS.equalsIgnoreCase(command)
                || UserImpersonationConstants.COMMAND_STOP_LOGIN_AS.equalsIgnoreCase(command);
    }
}
