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
package org.apache.fineract.portfolio.loanaccount.serialization;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.LocalDate;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.junit.jupiter.api.Test;

class SourceExactRefinancingQuoteDateTest {

    private static final LocalDate SUBMITTED = LocalDate.parse("2026-08-27");
    private static final LocalDate PAYOFF = LocalDate.parse("2026-08-28");
    private static final LocalDate CONTRACTUAL_START = LocalDate.parse("2026-10-08");

    @Test
    void ordinaryLoansContinueToQuoteOnExpectedDisbursementDate() {
        assertThat(LoanApplicationValidator.sourceExactRefinancingQuoteDate(false, null, CONTRACTUAL_START, SUBMITTED, false, null,
                false)).isEqualTo(CONTRACTUAL_START);
    }

    @Test
    void sourceRefinanceQuotesPredecessorOnPayoffDay() {
        assertThat(LoanApplicationValidator.sourceExactRefinancingQuoteDate(true, PAYOFF, CONTRACTUAL_START, SUBMITTED, true,
                "ARISSTO:CRD:2494", false)).isEqualTo(PAYOFF);
        assertThat(LoanApplicationValidator.sourceExactRefinancingQuoteDate(true, PAYOFF, CONTRACTUAL_START, SUBMITTED, true,
                "PROOF:hist-1597-oct17:ARISSTO:CRD:2494", false)).isEqualTo(PAYOFF);
    }

    @Test
    void quoteDateRequiresSourceRefinanceAndValidDateRange() {
        assertThrows(GeneralPlatformDomainRuleException.class, () -> LoanApplicationValidator.sourceExactRefinancingQuoteDate(true,
                PAYOFF, CONTRACTUAL_START, SUBMITTED, false, "ARISSTO:CRD:2494", false));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> LoanApplicationValidator.sourceExactRefinancingQuoteDate(true,
                PAYOFF, CONTRACTUAL_START, SUBMITTED, true, "ORDINARY:2494", false));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> LoanApplicationValidator.sourceExactRefinancingQuoteDate(true,
                SUBMITTED.minusDays(1), CONTRACTUAL_START, SUBMITTED, true, "ARISSTO:CRD:2494", false));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> LoanApplicationValidator.sourceExactRefinancingQuoteDate(true,
                CONTRACTUAL_START.plusDays(1), CONTRACTUAL_START, SUBMITTED, true, "ARISSTO:CRD:2494", false));
    }

    @Test
    void schedulePreviewAcceptsSourceQuoteBeforeExternalIdIsResolved() {
        assertThat(LoanApplicationValidator.sourceExactRefinancingQuoteDate(true, PAYOFF, CONTRACTUAL_START, SUBMITTED, true, null,
                true)).isEqualTo(PAYOFF);
    }
}
