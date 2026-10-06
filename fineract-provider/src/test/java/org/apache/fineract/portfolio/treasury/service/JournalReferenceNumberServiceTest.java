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
package org.apache.fineract.portfolio.treasury.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.ArgumentMatchers.startsWith;

import jakarta.persistence.EntityManager;
import jakarta.persistence.Query;
import java.time.LocalDate;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class JournalReferenceNumberServiceTest {

    @Test
    void monthlyCounterContinuesImportedMonthAndResetsInNextMonth() {
        EntityManager entityManager = mock(EntityManager.class);
        Query insertCounter = mock(Query.class);
        Query lockedCounter = mock(Query.class);
        Query assignment = mock(Query.class);
        Query maximum = mock(Query.class);
        Query update = mock(Query.class);
        Query insertAssignment = mock(Query.class);
        when(entityManager.createNativeQuery(anyString())).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.startsWith("INSERT INTO m_gl_journal_number_sequence")) {
                return insertCounter;
            }
            if (sql.startsWith("SELECT last_value")) {
                return lockedCounter;
            }
            if (sql.startsWith("SELECT period_key")) {
                return assignment;
            }
            if (sql.startsWith("SELECT COALESCE(MAX")) {
                return maximum;
            }
            if (sql.startsWith("UPDATE m_gl_journal_number_sequence")) {
                return update;
            }
            return insertAssignment;
        });
        for (Query query : java.util.List.of(insertCounter, lockedCounter, assignment, maximum, update, insertAssignment)) {
            when(query.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any())).thenReturn(query);
        }
        when(lockedCounter.getSingleResult()).thenReturn(0, 0);
        when(assignment.getResultList()).thenReturn(java.util.List.of());
        when(maximum.getSingleResult()).thenReturn(403, 0);
        JournalReferenceNumberService service = new JournalReferenceNumberService();
        ReflectionTestUtils.setField(service, "entityManager", entityManager);
        assertEquals("2024120404", service.assign("A|2024-12-31", LocalDate.of(2024, 12, 31)));
        assertEquals("2025010001", service.assign("B|2025-01-01", LocalDate.of(2025, 1, 1)));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.assign(LocalDate.of(2025, 1, 1)));
    }

    @Test
    void repeatedGroupReturnsItsOriginalNumberWithoutIncrementingCounter() {
        EntityManager entityManager = mock(EntityManager.class);
        Query insertCounter = mock(Query.class);
        Query lockedCounter = mock(Query.class);
        Query assignment = mock(Query.class);
        when(entityManager.createNativeQuery(anyString())).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.startsWith("INSERT INTO m_gl_journal_number_sequence")) {
                return insertCounter;
            }
            if (sql.startsWith("SELECT last_value")) {
                return lockedCounter;
            }
            if (sql.startsWith("SELECT period_key")) {
                return assignment;
            }
            throw new AssertionError("Unexpected allocation SQL: " + sql);
        });
        when(insertCounter.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any()))
                .thenReturn(insertCounter);
        when(lockedCounter.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any()))
                .thenReturn(lockedCounter);
        when(assignment.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any()))
                .thenReturn(assignment);
        when(lockedCounter.getSingleResult()).thenReturn(451);
        when(assignment.getResultList()).thenReturn(java.util.List.<Object[]>of(new Object[] { "202609", "2026090451", "GENERATED" }));
        JournalReferenceNumberService service = new JournalReferenceNumberService();
        ReflectionTestUtils.setField(service, "entityManager", entityManager);
        assertEquals("2026090451", service.assign("L123|2026-09-18", LocalDate.of(2026, 9, 18)));
        verify(entityManager, never()).createNativeQuery(startsWith("UPDATE m_gl_journal_number_sequence"));
    }

    @Test
    void importedNumberAlreadyOwnedByAnotherTransactionIsRejected() {
        EntityManager entityManager = mock(EntityManager.class);
        Query insertCounter = mock(Query.class);
        Query lockedCounter = mock(Query.class);
        Query assignment = mock(Query.class);
        Query collision = mock(Query.class);
        when(entityManager.createNativeQuery(anyString())).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.startsWith("INSERT INTO m_gl_journal_number_sequence")) {
                return insertCounter;
            }
            if (sql.startsWith("SELECT last_value")) {
                return lockedCounter;
            }
            if (sql.startsWith("SELECT period_key")) {
                return assignment;
            }
            if (sql.startsWith("SELECT COUNT(*) FROM acc_gl_journal_entry")) {
                return collision;
            }
            throw new AssertionError("Unexpected import SQL: " + sql);
        });
        for (Query query : java.util.List.of(insertCounter, lockedCounter, assignment, collision)) {
            when(query.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any())).thenReturn(query);
        }
        when(lockedCounter.getSingleResult()).thenReturn(0);
        when(assignment.getResultList()).thenReturn(java.util.List.of());
        when(collision.getSingleResult()).thenReturn(1L);
        JournalReferenceNumberService service = new JournalReferenceNumberService();
        ReflectionTestUtils.setField(service, "entityManager", entityManager);
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.reserveImported("AI123|2026-09-17", "AI123", "2026090446"));
    }

    @Test
    void seedUsesAssignedArisstoMaximumBeyondImportedJournals() {
        EntityManager entityManager = mock(EntityManager.class);
        Query invalid = mock(Query.class);
        Query imported = mock(Query.class);
        Query insert = mock(Query.class);
        Query lockedCounter = mock(Query.class);
        Query targetMaximum = mock(Query.class);
        when(entityManager.createNativeQuery(anyString())).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.startsWith("SELECT COUNT(*) FROM credesal_arissto_gl_journal")) {
                return invalid;
            }
            if (sql.startsWith("SELECT SUBSTRING(target_ref_num")) {
                return imported;
            }
            if (sql.startsWith("INSERT INTO m_gl_journal_number_sequence")) {
                return insert;
            }
            if (sql.startsWith("SELECT last_value")) {
                return lockedCounter;
            }
            return targetMaximum;
        });
        when(invalid.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any())).thenReturn(invalid);
        when(imported.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any())).thenReturn(imported);
        when(insert.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any())).thenReturn(insert);
        when(lockedCounter.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any()))
                .thenReturn(lockedCounter);
        when(targetMaximum.setParameter(org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.any()))
                .thenReturn(targetMaximum);
        when(invalid.getSingleResult()).thenReturn(0L);
        when(imported.getResultList()).thenReturn(java.util.List.<Object[]>of(new Object[] { "202609", 446 }));
        when(lockedCounter.getSingleResult()).thenReturn(0);
        when(targetMaximum.getSingleResult()).thenReturn(448);

        JournalReferenceNumberService service = new JournalReferenceNumberService();
        ReflectionTestUtils.setField(service, "entityManager", entityManager);

        var result = service.seedImported(LocalDate.of(2026, 9, 18), java.util.Map.of("202609", 450));
        assertEquals(450, ((java.util.Map<?, ?>) result.get("periods")).get("202609"));
        assertEquals(1, result.get("raised"));
    }
}
