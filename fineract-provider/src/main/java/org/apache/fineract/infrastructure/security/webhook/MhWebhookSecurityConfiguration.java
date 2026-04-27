package org.apache.fineract.infrastructure.security.webhook;

import static org.springframework.security.web.util.matcher.AntPathRequestMatcher.antMatcher;

import org.apache.fineract.infrastructure.businessdate.service.BusinessDateReadPlatformService;
import org.apache.fineract.infrastructure.security.service.AuthTenantDetailsService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.context.SecurityContextHolderFilter;

@Configuration
public class MhWebhookSecurityConfiguration {

    @Value("${mh.webhook.tenant-identifier:default}")
    private String webhookTenantIdentifier;

    @Bean
    @Order(0)
    public SecurityFilterChain mhWebhookSecurityFilterChain(HttpSecurity http, AuthTenantDetailsService tenantDetailsService,
            BusinessDateReadPlatformService businessDateReadPlatformService) throws Exception {
        http.securityMatcher(antMatcher("/api/*/webhooks/mh/validation-result")) //
                .csrf(AbstractHttpConfigurer::disable) //
                .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS)) //
                .authorizeHttpRequests(auth -> auth.requestMatchers(HttpMethod.POST, "/api/*/webhooks/mh/validation-result").permitAll()) //
                .addFilterBefore(new MhWebhookTenantFilter(tenantDetailsService, businessDateReadPlatformService, webhookTenantIdentifier),
                        SecurityContextHolderFilter.class);
        return http.build();
    }
}
