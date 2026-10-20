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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;

class LoanPortfolioAccountSelectionTest {

    @Test
    void selectsShortAndLongAccountsAtTheCalendarDayBoundary() {
        final LocalDate start = LocalDate.of(2026, 1, 1);
        final Loan shortLoan = loan(start, start.plusDays(366));
        final Loan longLoan = loan(start, start.plusDays(367));

        shortLoan.selectTermPortfolioAccount(10L, 20L);
        longLoan.selectTermPortfolioAccount(10L, 20L);

        assertThat(shortLoan.getPortfolioAccountGlId()).isEqualTo(10L);
        assertThat(shortLoan.getPortfolioAccountTermDays()).isEqualTo(366);
        assertThat(longLoan.getPortfolioAccountGlId()).isEqualTo(20L);
        assertThat(longLoan.getPortfolioAccountTermDays()).isEqualTo(367);
        assertThat(longLoan.getPortfolioAccountExpectedDisbursementDate()).isEqualTo(start);
        assertThat(longLoan.getPortfolioAccountExpectedMaturityDate()).isEqualTo(start.plusDays(367));
        assertThat(longLoan.getPortfolioAccountSelectionReason()).isEqualTo("EXPECTED_DATES_366_DAY_RULE");
    }

    @Test
    void actualDisbursementDoesNotChangeSelection() {
        final LocalDate start = LocalDate.of(2026, 1, 1);
        final Loan loan = loan(start, start.plusDays(367));
        loan.setActualDisbursementDate(start.minusDays(5));
        loan.selectTermPortfolioAccount(10L, 20L);
        loan.setActualDisbursementDate(start.plusDays(2));
        loan.selectTermPortfolioAccount(10L, 20L);

        assertThat(loan.getPortfolioAccountGlId()).isEqualTo(20L);
        assertThat(loan.getPortfolioAccountTermDays()).isEqualTo(367);
    }

    @Test
    void selectsPairedInterestReceivableAccountFromTheSameExpectedTerm() {
        final LocalDate start = LocalDate.of(2026, 1, 1);
        final Loan shortLoan = loan(start, start.plusDays(366));
        final Loan longLoan = loan(start, start.plusDays(367));

        shortLoan.selectTermPortfolioAccount(10L, 20L, 30L, 40L);
        longLoan.selectTermPortfolioAccount(10L, 20L, 30L, 40L);

        assertThat(shortLoan.getPortfolioInterestReceivableGlId()).isEqualTo(30L);
        assertThat(longLoan.getPortfolioInterestReceivableGlId()).isEqualTo(40L);
    }

    @Test
    void expectedDateRevisionCannotSilentlySwitchAccounts() {
        final LocalDate start = LocalDate.of(2026, 1, 1);
        final Loan loan = loan(start, start.plusDays(366));
        loan.selectTermPortfolioAccount(10L, 20L);
        loan.setExpectedMaturityDate(start.plusDays(367));

        assertThatThrownBy(() -> loan.selectTermPortfolioAccount(10L, 20L)).isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("reclassification is required");
        assertThatThrownBy(loan::validateTermPortfolioAccountSelection).isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("reclassification is required");
        assertThat(loan.getPortfolioAccountGlId()).isEqualTo(10L);
    }

    @Test
    void invalidContractDatesFailClosed() {
        final Loan loan = loan(LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 1));
        assertThatThrownBy(() -> loan.selectTermPortfolioAccount(10L, 20L)).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("valid expected disbursement and maturity dates");
    }

    private Loan loan(final LocalDate expectedDisbursement, final LocalDate expectedMaturity) {
        final Loan loan = new Loan();
        loan.setExpectedDisbursementDate(expectedDisbursement);
        loan.setExpectedMaturityDate(expectedMaturity);
        return loan;
    }
}
