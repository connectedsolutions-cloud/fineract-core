package org.apache.fineract.infrastructure.security.webhook;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.LocalDate;
import java.util.HashMap;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.businessdate.service.BusinessDateReadPlatformService;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.exception.InvalidTenantIdentifierException;
import org.apache.fineract.infrastructure.security.service.AuthTenantDetailsService;
import org.springframework.web.filter.OncePerRequestFilter;

@RequiredArgsConstructor
public class MhWebhookTenantFilter extends OncePerRequestFilter {

    private final AuthTenantDetailsService tenantDetailsService;
    private final BusinessDateReadPlatformService businessDateReadPlatformService;
    private final String defaultTenantIdentifier;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        ThreadLocalContextUtil.reset();
        try {
            FineractPlatformTenant tenant = tenantDetailsService.loadTenantById(defaultTenantIdentifier, false);
            ThreadLocalContextUtil.setTenant(tenant);
            HashMap<BusinessDateType, LocalDate> businessDates = businessDateReadPlatformService.getBusinessDates();
            ThreadLocalContextUtil.setBusinessDates(businessDates);
            filterChain.doFilter(request, response);
        } catch (InvalidTenantIdentifierException e) {
            response.sendError(HttpServletResponse.SC_BAD_REQUEST, e.getMessage());
        } finally {
            ThreadLocalContextUtil.reset();
        }
    }
}
