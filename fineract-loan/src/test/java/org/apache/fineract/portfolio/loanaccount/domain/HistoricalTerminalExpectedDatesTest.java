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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.domain;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.portfolio.loanaccount.service.SourceExactTerminalAdjustmentContext;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class HistoricalTerminalExpectedDatesTest {
    private Loan loan() {
        var loan = new Loan();
        LocalDate start = LocalDate.of(2024, 1, 1);
        loan.setExpectedDisbursementDate(start);
        loan.setExpectedMaturityDate(start.plusDays(365));
        loan.selectTermPortfolioAccount(10L, 20L);
        ReflectionTestUtils.setField(loan, "externalId", new ExternalId("ARISSTO:CRD:1"));
        var detail = mock(LoanProductRelatedDetail.class);
        ReflectionTestUtils.setField(loan, "loanRepaymentScheduleDetail", detail);
        var row = mock(LoanRepaymentScheduleInstallment.class);
        when(row.getDueDate()).thenReturn(start.plusDays(367));
        ReflectionTestUtils.setField(loan, "repaymentScheduleInstallments", List.of(row));
        return loan;
    }

    @Test
    void historicalTerminalBalanceRefreshPreservesSelectedExpectedTermAndAccount() {
        Loan loan = loan();
        LocalDate expected = loan.getExpectedMaturityDate();
        SourceExactTerminalAdjustmentContext.execute(() -> {
            loan.updateLoanScheduleDependentDerivedFields();
            loan.validateTermPortfolioAccountSelection();
            return null;
        });
        assertEquals(expected, loan.getExpectedMaturityDate());
        assertEquals(10L, loan.getPortfolioAccountGlId());
        assertFalse(SourceExactTerminalAdjustmentContext.isActive());
    }

    @Test
    void ordinaryScheduleChangeStillRequiresExplicitReclassification() {
        Loan loan = loan();
        loan.updateLoanScheduleDependentDerivedFields();
        assertThrows(RuntimeException.class, loan::validateTermPortfolioAccountSelection);
    }

    @Test
    void terminalContextNeverLeaksAfterAnException() {
        assertThrows(IllegalStateException.class, () -> SourceExactTerminalAdjustmentContext.execute(() -> {
            throw new IllegalStateException("test");
        }));
        assertFalse(SourceExactTerminalAdjustmentContext.isActive());
    }
}
