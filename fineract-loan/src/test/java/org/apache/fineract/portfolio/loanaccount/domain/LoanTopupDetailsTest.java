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
package org.apache.fineract.portfolio.loanaccount.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.mockito.Mockito.mock;

import java.util.List;
import org.junit.jupiter.api.Test;

class LoanTopupDetailsTest {

    @Test
    void shouldRepresentSingleLoanRefinancingThroughCompatibilityAggregate() {
        final LoanTopupDetails refinancing = new LoanTopupDetails(mock(Loan.class), 31L);

        assertThat(refinancing.getOperationType()).isEqualTo("SINGLE_REFINANCE");
        assertThat(refinancing.isConsolidation()).isFalse();
        assertThat(refinancing.getLoanIdsToClose()).containsExactly(31L);
    }

    @Test
    void shouldOrderConsolidationPredecessorsDeterministically() {
        final LoanTopupDetails refinancing = new LoanTopupDetails(mock(Loan.class), List.of(44L, 12L));

        assertThat(refinancing.getOperationType()).isEqualTo("CONSOLIDATION");
        assertThat(refinancing.isConsolidation()).isTrue();
        assertThat(refinancing.getLoanIdToClose()).isEqualTo(12L);
        assertThat(refinancing.getLoanIdsToClose()).containsExactly(12L, 44L);
    }

    @Test
    void shouldRejectDuplicateOrEmptyPredecessors() {
        final Loan loan = mock(Loan.class);

        assertThatIllegalArgumentException().isThrownBy(() -> new LoanTopupDetails(loan, List.of()));
        assertThatIllegalArgumentException().isThrownBy(() -> new LoanTopupDetails(loan, List.of(12L, 12L)));
    }
}
