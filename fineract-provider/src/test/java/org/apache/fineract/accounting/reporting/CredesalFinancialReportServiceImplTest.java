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
package org.apache.fineract.accounting.reporting;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class CredesalFinancialReportServiceImplTest {

    private final NamedParameterJdbcTemplate jdbcTemplate = mock(NamedParameterJdbcTemplate.class);
    private final PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
    private final AppUser user = mock(AppUser.class);
    private final CredesalFinancialReportServiceImpl service = new CredesalFinancialReportServiceImpl(jdbcTemplate, securityContext);

    @Test
    void returnsDimensionAwareTrialBalanceWithFrozenPresentationIdentity() {
        when(securityContext.authenticatedUser()).thenReturn(user);
        when(jdbcTemplate.queryForObject(anyString(), anyMap(), eq(Integer.class))).thenReturn(1);
        when(jdbcTemplate.queryForObject(anyString(), any(SqlParameterSource.class), eq(Integer.class))).thenReturn(0);
        when(jdbcTemplate.queryForMap(anyString(), anyMap())).thenReturn(Map.of("presentation_version", "arissto-coa-presentation-v1",
                "source_snapshot_sha256", "a".repeat(64), "version_count", 1L, "hash_count", 1L));
        when(jdbcTemplate.queryForList(anyString(), any(SqlParameterSource.class)))
                .thenReturn(List.of(Map.of("opening_balance", BigDecimal.ZERO, "debits", BigDecimal.TEN, "credits", BigDecimal.TEN,
                        "closing_balance", BigDecimal.ZERO)));
        when(jdbcTemplate.queryForMap(anyString(), any(SqlParameterSource.class))).thenReturn(Map.of("debits", BigDecimal.TEN,
                "credits", BigDecimal.TEN, "trial_balance_variance", BigDecimal.ZERO, "assets", BigDecimal.ZERO, "liabilities",
                BigDecimal.ZERO, "equity", BigDecimal.ZERO, "income", BigDecimal.ZERO, "expense", BigDecimal.ZERO));

        CredesalFinancialReportData result = service.run("trial-balance", LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 31),
                "1", "post-closing", true);

        assertThat(result.presentationVersion()).isEqualTo("arissto-coa-presentation-v1");
        assertThat(result.officeExternalId()).isEqualTo("1");
        assertThat(result.rows()).hasSize(1);
        assertThat(result.controls()).containsEntry("trial_balance_variance", BigDecimal.ZERO).containsEntry("dimension_scope", "agency");
        ArgumentCaptor<String> reportSql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<SqlParameterSource> reportParameters = ArgumentCaptor.forClass(SqlParameterSource.class);
        verify(jdbcTemplate).queryForList(reportSql.capture(), reportParameters.capture());
        assertThat(reportSql.getValue()).contains("current_annual_closing")
                .contains("tree.classifier_code NOT IN ('004', '005')")
                .contains(":reportType = 'income-statement' AND classifier_code = '005'");
        assertThat(reportParameters.getValue().getValue("financialYearStart")).isEqualTo(LocalDate.of(2026, 1, 1));
        verify(user).validateHasPermissionTo("READ_CREDESAL_FINANCIAL_REPORTS");
    }

    @Test
    void failsClosedWhenNativeOfficeAndCanonicalDimensionDisagree() {
        when(securityContext.authenticatedUser()).thenReturn(user);
        when(jdbcTemplate.queryForObject(anyString(), any(SqlParameterSource.class), eq(Integer.class))).thenReturn(1);

        assertThatThrownBy(() -> service.run("trial-balance", LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 31), null,
                "post-closing", true)).isInstanceOf(GeneralPlatformDomainRuleException.class)
                        .hasMessageContaining("office dimensions");
    }

    @Test
    void rejectsUnsupportedReportTypesBeforeQueryingTheLedger() {
        when(securityContext.authenticatedUser()).thenReturn(user);

        assertThatThrownBy(() -> service.run("legacy-template", LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 31), null,
                "post-closing", true)).isInstanceOf(GeneralPlatformDomainRuleException.class);
    }
}
