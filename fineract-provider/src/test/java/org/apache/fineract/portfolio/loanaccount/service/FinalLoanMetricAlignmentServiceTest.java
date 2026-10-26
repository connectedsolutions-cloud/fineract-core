/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software distributed under the License is
 * distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.google.gson.Gson;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.fineract.accounting.cutoff.*;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.portfolio.charge.domain.*;
import org.apache.fineract.portfolio.loanaccount.domain.*;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.springframework.jdbc.core.JdbcTemplate;

class FinalLoanMetricAlignmentServiceTest {

    private final LoanRepositoryWrapper loans = mock(LoanRepositoryWrapper.class);
    private final ChargeRepositoryWrapper charges = mock(ChargeRepositoryWrapper.class);
    private final AccountingCutoffMigrationValidationService cutoff = mock(AccountingCutoffMigrationValidationService.class);
    private final PlatformSecurityContext security = mock(PlatformSecurityContext.class);
    private final AppUser user = mock(AppUser.class);
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final AccountingPostingContext context = new AccountingPostingContext();
    private final AccountingOperationalMigrationService migration = new AccountingOperationalMigrationService(security, context);
    private final FinalLoanMetricAlignmentService service = new FinalLoanMetricAlignmentService(loans, charges, migration, cutoff, security,
            jdbc);
    private final Loan loan = mock(Loan.class);
    private final Map<String, BigDecimal> before = vector("1.00"), targets = vector("2.00");
    private final AtomicReference<Map<String, BigDecimal>> state = new AtomicReference<>(before);

    FinalLoanMetricAlignmentServiceTest() {
        when(security.authenticatedUser()).thenReturn(user); when(user.getId()).thenReturn(1L);
        when(loans.findOneWithNotFoundDetection(42L,true)).thenReturn(loan);
        when(loan.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD:2612"));
        when(loan.getStatus()).thenReturn(LoanStatus.ACTIVE); when(loan.getCurrency()).thenReturn(new MonetaryCurrency("USD",2,0));
        when(jdbc.queryForObject(anyString(),eq(Long.class),any(Object[].class))).thenAnswer(i->i.getArgument(0,String.class).contains("COUNT")?0L:42L);
        when(jdbc.queryForList(anyString(),any(Object[].class))).thenReturn(List.of());
        definition(3L,false,1,2); definition(4L,true,1,2); definition(5L,false,8,8);
    }

    private void definition(long id, boolean penalty, int calculation, int time) {
        Charge c = mock(Charge.class);
        when(c.isActive()).thenReturn(true);
        when(c.isLoanCharge()).thenReturn(true);
        when(c.isPenalty()).thenReturn(penalty);
        when(c.getCurrencyCode()).thenReturn("USD");
        when(c.getChargeCalculation()).thenReturn(calculation);
        when(c.getChargeTimeType()).thenReturn(time);
        when(charges.findOneWithNotFoundDetection(id)).thenReturn(c);
    }

    private MockedStatic<FinalLoanMetrics> domain() {
        MockedStatic<FinalLoanMetrics> mocked = mockStatic(FinalLoanMetrics.class, CALLS_REAL_METHODS);
        mocked.when(() -> FinalLoanMetrics.read(eq(loan), any(), any())).thenAnswer(i -> state.get());
        mocked.when(() -> FinalLoanMetrics.apply(eq(loan), any(), any(), any(), any(), any())).thenAnswer(i -> {
            assertEquals(AccountingPostingOrigin.ARISSTO_OPERATIONAL_MIGRATION, context.getOrigin());
            state.set(targets);
            return null;
        });
        return mocked;
    }

    @Test
    void appliesWithinMigrationContextAuditsAndRepeatedRequestDoesNotAdjustTwice() {
        AtomicReference<String> hash = new AtomicReference<>();
        when(jdbc.queryForList(startsWith("SELECT payload_hash"), any(Object[].class)))
                .thenAnswer(i -> hash.get() == null ? List.of() : List.of(Map.of("payload_hash", hash.get())));
        when(jdbc.update(startsWith("INSERT INTO credesal_loan_metric_alignment"), any(Object[].class))).thenAnswer(i -> {
            hash.set(i.getArgument(3));
            return 1;
        });
        try (var domain = domain()) {
            assertEquals(targets, service.align(42L, request(before, targets)).get("metrics"));
            assertEquals(true, service.align(42L, request(before, targets)).get("alreadyApplied"));
            domain.verify(() -> FinalLoanMetrics.apply(eq(loan), any(), any(), any(), any(), any()), times(1));
        }
        verify(loans, times(1)).saveAndFlush(loan);
        verify(user, times(2)).validateHasPermissionTo(AccountingOperationalMigrationService.PERMISSION);
        verify(cutoff, times(2)).requireExactActiveCutoff(LocalDate.of(2026, 10, 20));
        assertEquals(AccountingPostingOrigin.NATIVE_OPERATION, context.getOrigin());
    }

    @Test
    void rejectsStaleComparisonBeforeNativeWrites() {
        try (var domain = domain()) {
            assertThrows(RuntimeException.class, () -> service.align(42L, request(targets, targets)));
            domain.verify(() -> FinalLoanMetrics.apply(eq(loan), any(), any(), any(), any(), any()), never());
        }
        verify(loans, never()).saveAndFlush(any());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test void rejectsAnyChangedLinkedJournalAndDoesNotWriteSuccessAudit() {
        when(jdbc.queryForList(startsWith("SELECT j.*"),any(Object[].class))).thenReturn(List.of(Map.of("id",1L,"amount",1)),List.of(Map.of("id",1L,"amount",2)));
        try(var domain=domain()) { assertThrows(RuntimeException.class,()->service.align(42L,request(before,targets))); }
        verify(jdbc,never()).update(startsWith("INSERT INTO credesal_loan_metric_alignment"),any(Object[].class));
        assertEquals(AccountingPostingOrigin.NATIVE_OPERATION,context.getOrigin());
    }

    @Test
    void rejectsWrongPermissionBeforeAnyDatabaseAccess() {
        doThrow(new IllegalStateException("denied")).when(user).validateHasPermissionTo(AccountingOperationalMigrationService.PERMISSION);
        assertThrows(RuntimeException.class, () -> service.align(42L, request(before, targets)));
        verifyNoInteractions(jdbc, loans, charges);
    }

    private static Map<String, BigDecimal> vector(String value) {
        Map<String, BigDecimal> result = new LinkedHashMap<>();
        for (String key : FinalLoanMetrics.KEYS)
            result.put(key, new BigDecimal(value));
        return result;
    }

    private static String request(Map<String, BigDecimal> expected, Map<String, BigDecimal> targets) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("sourceSystem", "ARISSTO");
        r.put("sourceLoanExternalId", "ARISSTO:CRD:2612");
        r.put("cutoffDate", "2026-10-20");
        r.put("requestId", "test-request");
        r.put("sourceObservedAt", "2026-10-26T15:00:00Z");
        r.put("insuranceChargeId", 3);
        r.put("recurringInsuranceChargeId", 5);
        r.put("penaltyChargeId", 4);
        r.put("expected", expected);
        r.put("targets", targets);
        return new Gson().toJson(r);
    }
}
