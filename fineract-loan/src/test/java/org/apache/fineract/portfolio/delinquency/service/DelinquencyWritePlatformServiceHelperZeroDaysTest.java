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
package org.apache.fineract.portfolio.delinquency.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.portfolio.delinquency.domain.DelinquencyBucket;
import org.apache.fineract.portfolio.delinquency.domain.DelinquencyRange;
import org.apache.fineract.portfolio.delinquency.domain.DelinquencyRangeRepository;
import org.apache.fineract.portfolio.delinquency.domain.LoanDelinquencyTagHistory;
import org.apache.fineract.portfolio.delinquency.domain.LoanDelinquencyTagHistoryRepository;
import org.apache.fineract.portfolio.delinquency.domain.LoanInstallmentDelinquencyTagRepository;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;

class DelinquencyWritePlatformServiceHelperZeroDaysTest {

    private final BusinessEventNotifierService events = mock(BusinessEventNotifierService.class);
    private final LoanDelinquencyTagHistoryRepository history = mock(LoanDelinquencyTagHistoryRepository.class);
    private final DelinquencyRangeRepository ranges = mock(DelinquencyRangeRepository.class);
    private final DelinquencyWritePlatformServiceHelper helper = new DelinquencyWritePlatformServiceHelper(events, history, ranges,
            mock(LoanInstallmentDelinquencyTagRepository.class));

    @Test
    void recordsA1AtZeroDaysWhenBucketStartsAtZero() {
        Loan loan = mock(Loan.class);
        DelinquencyRange a1 = range(1L, 0, 7);
        DelinquencyBucket bucket = bucket(a1);
        LocalDate businessDate = LocalDate.of(2026, 10, 8);
        when(loan.isOpen()).thenReturn(true);
        when(history.findByLoanAndLiftedOnDate(loan, null)).thenReturn(Optional.empty());
        when(ranges.getReferenceById(1L)).thenReturn(a1);

        try (MockedStatic<DateUtils> dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(businessDate);
            helper.applyDelinquencyForLoan(loan, bucket, 0);
        }

        ArgumentCaptor<List<LoanDelinquencyTagHistory>> saved = historyCaptor();
        verify(history).saveAllAndFlush(saved.capture());
        assertEquals(1, saved.getValue().size());
        assertEquals(a1, saved.getValue().get(0).getDelinquencyRange());
        assertEquals(businessDate, saved.getValue().get(0).getAddedOnDate());
        assertNull(saved.getValue().get(0).getLiftedOnDate());
    }

    @Test
    void liftsExistingTagAtZeroDaysWhenBucketHasNoZeroRange() {
        Loan loan = mock(Loan.class);
        DelinquencyRange a1 = range(1L, 1, 7);
        DelinquencyBucket bucket = bucket(a1);
        LoanDelinquencyTagHistory current = new LoanDelinquencyTagHistory(a1, loan, LocalDate.of(2026, 10, 7), null);
        LocalDate businessDate = LocalDate.of(2026, 10, 8);
        when(loan.isOpen()).thenReturn(true);
        when(history.findByLoanAndLiftedOnDate(loan, null)).thenReturn(Optional.of(current));

        try (MockedStatic<DateUtils> dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(businessDate);
            helper.applyDelinquencyForLoan(loan, bucket, 0);
        }

        ArgumentCaptor<List<LoanDelinquencyTagHistory>> saved = historyCaptor();
        verify(history).saveAllAndFlush(saved.capture());
        assertEquals(List.of(current), saved.getValue());
        assertEquals(businessDate, current.getLiftedOnDate());
    }

    private static DelinquencyRange range(Long id, int minimum, int maximum) {
        DelinquencyRange range = mock(DelinquencyRange.class);
        when(range.getId()).thenReturn(id);
        when(range.getMinimumAgeDays()).thenReturn(minimum);
        when(range.getMaximumAgeDays()).thenReturn(maximum);
        return range;
    }

    private static DelinquencyBucket bucket(DelinquencyRange range) {
        DelinquencyBucket bucket = new DelinquencyBucket("test");
        bucket.setRanges(new ArrayList<>(List.of(range)));
        return bucket;
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    private static ArgumentCaptor<List<LoanDelinquencyTagHistory>> historyCaptor() {
        return ArgumentCaptor.forClass((Class) List.class);
    }
}
