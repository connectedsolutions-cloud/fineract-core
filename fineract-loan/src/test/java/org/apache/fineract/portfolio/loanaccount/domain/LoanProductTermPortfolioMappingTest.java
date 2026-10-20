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

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.gson.JsonElement;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.productaccountmapping.service.LoanProductToGLAccountMappingHelper;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMapping;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMappingRepository;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.PortfolioProductType;
import org.junit.jupiter.api.Test;

class LoanProductTermPortfolioMappingTest {

    private final ProductToGLAccountMappingRepository mappings = mock(ProductToGLAccountMappingRepository.class);
    private final LoanRepository loans = mock(LoanRepository.class);
    private final FromJsonHelper json = new FromJsonHelper();
    private final LoanProductToGLAccountMappingHelper helper = new LoanProductToGLAccountMappingHelper(null, mappings, json, null,
            null, null, null, loans);

    @Test
    void newProductRequiresDistinctAccountsWhenTermPolicyIsEnabled() {
        final JsonElement same = json.parse("{\"loanPortfolioAccountId\":10,\"longTermLoanPortfolioAccountId\":10}");
        final JsonElement different = json.parse("{\"loanPortfolioAccountId\":10,\"longTermLoanPortfolioAccountId\":20}");

        assertThatThrownBy(() -> helper.validateDistinctPortfolioAccounts(same, null))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("must be different");
        assertThatCode(() -> helper.validateDistinctPortfolioAccounts(different, null)).doesNotThrowAnyException();
    }

    @Test
    void existingDisbursedLoansRequireReviewedRepairBeforePolicyOptIn() {
        when(mappings.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                CashAccountsForLoan.LOAN_PORTFOLIO.getValue())).thenReturn(mapping(10L));
        when(loans.countDisbursedLoansWithoutSelectedPortfolioAccount(2L)).thenReturn(1L);
        final JsonElement requested = json.parse("{\"longTermLoanPortfolioAccountId\":20}");

        assertThatThrownBy(() -> helper.validateDistinctPortfolioAccounts(requested, 2L))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("reviewed accounting migration");
    }

    @Test
    void accrualTermPolicyRequiresDistinctInterestReceivableAccounts() {
        final JsonElement missingLongInterest = json.parse(
                "{\"accountingRule\":3,\"loanPortfolioAccountId\":10,\"longTermLoanPortfolioAccountId\":20,\"receivableInterestAccountId\":30}");
        final JsonElement complete = json.parse(
                "{\"accountingRule\":3,\"loanPortfolioAccountId\":10,\"longTermLoanPortfolioAccountId\":20,\"receivableInterestAccountId\":30,\"longTermInterestReceivableAccountId\":40}");

        assertThatThrownBy(() -> helper.validateDistinctPortfolioAccounts(missingLongInterest, null))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("interest receivable accounts");
        assertThatCode(() -> helper.validateDistinctPortfolioAccounts(complete, null)).doesNotThrowAnyException();
    }

    @Test
    void longInterestReceivableCannotBeConfiguredWithoutLongPortfolio() {
        final JsonElement orphanInterest = json.parse(
                "{\"accountingRule\":3,\"loanPortfolioAccountId\":10,\"receivableInterestAccountId\":30,\"longTermInterestReceivableAccountId\":40}");

        assertThatThrownBy(() -> helper.validateDistinctPortfolioAccounts(orphanInterest, null))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("requires a long-term loan portfolio");
    }

    private ProductToGLAccountMapping mapping(final Long id) {
        final GLAccount account = new GLAccount();
        account.setId(id);
        return new ProductToGLAccountMapping().setGlAccount(account);
    }
}
