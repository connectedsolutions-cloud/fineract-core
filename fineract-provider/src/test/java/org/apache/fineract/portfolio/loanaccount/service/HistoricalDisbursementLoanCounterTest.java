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
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanBuilder;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.apache.fineract.portfolio.loanaccount.domain.LoanSummary;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

/** Characterizes native historical-disbursement counter effects without touching a tenant. */
@ExtendWith(MockitoExtension.class)
class HistoricalDisbursementLoanCounterTest {

    private static final LocalDate INSERTED_DATE = LocalDate.of(2023, 7, 24);
    private static final Long CLIENT_ID = 767L;
    @Mock
    private LoanRepositoryWrapper repository;
    @InjectMocks
    private LoanWritePlatformServiceJpaRepositoryImpl service;
    private Client client;

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 10, 27))));
        client = mock(Client.class);
        when(client.getId()).thenReturn(CLIENT_ID);
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void inserting125Before383ResequencesOnlyTheProductCounterWhenBorrowerCyclesAreDisabled() throws Exception {
        LoanProduct product = product(2L, false);
        Loan inserted = loan(product, 1154L, "125", null, null);
        Loan earlier = loan(product, 40L, "43", LocalDate.of(2023, 5, 19), 1);
        Loan later = loan(product, 261L, "383", LocalDate.of(2023, 12, 16), 2);
        Map<String, Object> before = state(later), earlierBefore = state(earlier);
        configure(product, INSERTED_DATE, List.of(later), null, 2);

        counterStage(inserted, INSERTED_DATE);

        assertEquals(2, inserted.getLoanProductLoanCounter());
        assertEquals(3, later.getLoanProductLoanCounter());
        assertNull(inserted.getCurrentLoanCounter());
        assertNull(later.getCurrentLoanCounter());
        assertEquals(Set.of("loanProductCounter"), changed(before, state(later)));
        assertEquals(earlierBefore, state(earlier));
        verify(repository).getClientOrJLGLoansDisbursedAfter(INSERTED_DATE, CLIENT_ID);
        verify(repository).save(List.of(later));
    }

    @Test
    void insertingOneHistoricalLoanShiftsEveryLaterSameProductLoanExactlyOnce() throws Exception {
        LoanProduct product = product(2L, false);
        Loan inserted = loan(product, 1154L, "125", null, null);
        Loan first = loan(product, 261L, "383", LocalDate.of(2023, 12, 16), 2);
        Loan second = loan(product, 262L, "384", LocalDate.of(2024, 1, 16), 3);
        Map<String, Object> beforeFirst = state(first), beforeSecond = state(second);
        configure(product, INSERTED_DATE, List.of(first, second), null, 3);
        counterStage(inserted, INSERTED_DATE);
        assertEquals(2, inserted.getLoanProductLoanCounter());
        assertEquals(3, first.getLoanProductLoanCounter());
        assertEquals(4, second.getLoanProductLoanCounter());
        assertEquals(Set.of("loanProductCounter"), changed(beforeFirst, state(first)));
        assertEquals(Set.of("loanProductCounter"), changed(beforeSecond, state(second)));
    }

    @Test
    void laterLoanOfAnotherProductKeepsItsProductCounter() throws Exception {
        LoanProduct product = product(2L, false), other = product(9L, false);
        Loan inserted = loan(product, 1154L, "125", null, null);
        Loan later = loan(product, 261L, "383", LocalDate.of(2023, 12, 16), 2);
        Loan unrelatedProduct = loan(other, 999L, "999", LocalDate.of(2024, 1, 16), 4);
        Map<String, Object> before = state(unrelatedProduct);
        configure(product, INSERTED_DATE, List.of(later, unrelatedProduct), null, 2);
        counterStage(inserted, INSERTED_DATE);
        assertEquals(3, later.getLoanProductLoanCounter());
        assertEquals(before, state(unrelatedProduct));
    }

    @Test
    void appendingAfterExistingLoansDoesNotTouchTheirCounters() throws Exception {
        LoanProduct product = product(2L, false);
        Loan inserted = loan(product, 1154L, "125", null, null);
        Loan previous = loan(product, 261L, "383", LocalDate.of(2023, 12, 16), 3);
        Map<String, Object> before = state(previous);
        LocalDate laterDate = LocalDate.of(2024, 2, 1);
        configure(product, laterDate, List.of(), null, 3);
        counterStage(inserted, laterDate);
        assertEquals(4, inserted.getLoanProductLoanCounter());
        assertEquals(before, state(previous));
    }

    @Test
    void enabledBorrowerCyclesAlsoResequenceTheirSeparateOverallCounter() throws Exception {
        LoanProduct product = product(2L, true);
        Loan inserted = loan(product, 1154L, "125", null, null);
        Loan later = loan(product, 261L, "383", LocalDate.of(2023, 12, 16), 2);
        later.updateClientLoanCounter(2);
        Map<String, Object> before = state(later);
        configure(product, INSERTED_DATE, List.of(later), 2, 2);
        counterStage(inserted, INSERTED_DATE);
        assertEquals(2, inserted.getCurrentLoanCounter());
        assertEquals(3, later.getCurrentLoanCounter());
        assertEquals(Set.of("loanCounter", "loanProductCounter"), changed(before, state(later)));
    }

    private LoanProduct product(long id, boolean includeInBorrowerCycle) {
        LoanProduct product = mock(LoanProduct.class);
        when(product.getId()).thenReturn(id);
        when(product.isIncludeInBorrowerCycle()).thenReturn(includeInBorrowerCycle);
        when(product.getLoanProductRelatedDetail()).thenReturn(mock(LoanProductRelatedDetail.class));
        return product;
    }

    private Loan loan(LoanProduct product, long id, String external, LocalDate disbursed, Integer productCounter) {
        Loan loan = new LoanBuilder(product).withClient(client).withId(id).withExternalId(new ExternalId("ARISSTO:CRD:" + external))
                .withActualDisbursementDate(disbursed).withLoanStatus(disbursed == null ? LoanStatus.APPROVED : LoanStatus.ACTIVE)
                .withProposedPrincipal(new BigDecimal("700.00")).withApprovedPrincipal(new BigDecimal("700.00"))
                .withNetDisbursalAmount(new BigDecimal("700.00")).build();
        ReflectionTestUtils.setField(loan.getSummary(), "totalPrincipalDisbursed", new BigDecimal("700.00"));
        ReflectionTestUtils.setField(loan.getSummary(), "totalPrincipalRepaid", new BigDecimal("100.00"));
        ReflectionTestUtils.setField(loan.getSummary(), "totalPrincipalOutstanding", new BigDecimal("600.00"));
        loan.updateLoanProductLoanCounter(productCounter);
        return loan;
    }

    private void configure(LoanProduct product, LocalDate date, List<Loan> later, Integer overallMax, int productMax) {
        when(repository.getClientOrJLGLoansDisbursedAfter(date, CLIENT_ID)).thenReturn(later);
        when(repository.getMaxClientOrJLGLoanCounter(CLIENT_ID)).thenReturn(overallMax);
        when(repository.getMaxClientOrJLGLoanProductCounter(product.getId(), CLIENT_ID)).thenReturn(productMax);
    }

    private void counterStage(Loan inserted, LocalDate date) {
        // This private stage is invoked by the public source-exact refinancing disbursement path.
        // Repository selection/persistence are mocked; the counter algorithm and Loan entities are real.
        ReflectionTestUtils.invokeMethod(service, "updateLoanCounters", inserted, date);
    }

    private Map<String, Object> state(Object entity) throws Exception {
        Map<String, Object> fields = new LinkedHashMap<>();
        for (Class<?> type = entity.getClass(); type != Object.class; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                // Woven lazy-loading value holders are not persisted business fields.
                // Reading the existing product initializes them without changing its FK.
                if (!Modifier.isStatic(field.getModifiers()) && !field.getName().startsWith("_persistence_")) {
                    field.setAccessible(true);
                    Object value = field.get(entity);
                    fields.put(field.getName(), value instanceof LoanSummary ? state(value) : value);
                }
            }
        }
        return fields;
    }

    private Set<String> changed(Map<String, Object> before, Map<String, Object> after) {
        return before.keySet().stream().filter(key -> !Objects.equals(before.get(key), after.get(key))).collect(Collectors.toSet());
    }
}
