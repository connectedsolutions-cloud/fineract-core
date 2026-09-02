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
package org.apache.fineract.portfolio.savings.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.apache.fineract.portfolio.savings.SavingsAccountTransactionType;
import org.apache.fineract.portfolio.savings.exception.SavingsExplicitInterestPostingException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class SavingsAccountExplicitInterestPostingTest {

    private static final LocalDate POSTING_DATE = LocalDate.of(2025, 6, 30);
    private static final String SOURCE_REFERENCE = "AHO_MOVIMIENTOS|1102";
    private static final String TENANT_IDENTIFIER = "explicit-interest-test";

    @BeforeEach
    void setUpTenantRounding() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, TENANT_IDENTIFIER, "Explicit interest test", "UTC", null));
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, POSTING_DATE)));
        MoneyHelper.initializeTenantRoundingMode(TENANT_IDENTIFIER, 6);
    }

    @AfterEach
    void clearTenantRounding() {
        ThreadLocalContextUtil.reset();
        MoneyHelper.clearCacheForTenant(TENANT_IDENTIFIER);
    }

    @Test
    void shouldCreateReferencedNativeInterestPostingWithExactSourceAmount() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT);

        final SavingsAccountTransaction transaction = account.createExplicitInterestPostingTransaction(new BigDecimal("4.17"), POSTING_DATE,
                SOURCE_REFERENCE, false);

        assertThat(transaction.getTransactionType()).isEqualTo(SavingsAccountTransactionType.INTEREST_POSTING);
        assertThat(transaction.getAmount()).isEqualByComparingTo("4.17");
        assertThat(transaction.getTransactionDate()).isEqualTo(POSTING_DATE);
        assertThat(transaction.getRefNo()).isEqualTo(SOURCE_REFERENCE);
        assertThat(transaction.isManualTransaction()).isTrue();
        assertThat(transaction.isReferencedManualInterestPosting()).isTrue();
        assertThat(account.getTransactions()).containsExactly(transaction);
    }

    @Test
    void shouldCreateReferencedNativeInterestPostingOnFixedDepositAccount() {
        final SavingsAccount account = savingsAccount(DepositAccountType.FIXED_DEPOSIT);

        final SavingsAccountTransaction transaction = account.createExplicitInterestPostingTransaction(new BigDecimal("4.17"), POSTING_DATE,
                SOURCE_REFERENCE, false);

        assertThat(transaction.getTransactionType()).isEqualTo(SavingsAccountTransactionType.INTEREST_POSTING);
        assertThat(transaction.getAmount()).isEqualByComparingTo("4.17");
        assertThat(transaction.getRefNo()).isEqualTo(SOURCE_REFERENCE);
        assertThat(transaction.isReferencedManualInterestPosting()).isTrue();
    }

    @Test
    void shouldReplaceCalculatedPostingOnTheSameHistoricalDate() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT);
        final SavingsAccountTransaction calculated = SavingsAccountTransaction.interestPosting(account, null, POSTING_DATE,
                org.apache.fineract.organisation.monetary.domain.Money.of(
                        new MonetaryCurrency("USD", 2, 1), new BigDecimal("4.16")), false);
        account.addTransaction(calculated);

        final SavingsAccountTransaction explicit = account.createExplicitInterestPostingTransaction(new BigDecimal("4.17"), POSTING_DATE,
                SOURCE_REFERENCE, false);

        assertThat(calculated.isReversed()).isTrue();
        assertThat(explicit.isReferencedManualInterestPosting()).isTrue();
        assertThat(account.getTransactions()).containsExactly(calculated, explicit);
    }

    @Test
    void shouldRejectMissingReferenceOrNonPositiveAmount() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT);

        assertThatThrownBy(() -> account.createExplicitInterestPostingTransaction(BigDecimal.ZERO, POSTING_DATE, SOURCE_REFERENCE, false))
                .isInstanceOf(SavingsExplicitInterestPostingException.class).hasMessageContaining("amount.must.be.positive");
        assertThatThrownBy(() -> account.createExplicitInterestPostingTransaction(new BigDecimal("4.17"), POSTING_DATE, " ", false))
                .isInstanceOf(SavingsExplicitInterestPostingException.class).hasMessageContaining("reference.required");
    }

    private SavingsAccount savingsAccount(final DepositAccountType depositAccountType) {
        final SavingsAccount account = new SavingsAccount();
        ReflectionTestUtils.setField(account, "depositType", depositAccountType.getValue());
        ReflectionTestUtils.setField(account, "currency", new MonetaryCurrency("USD", 2, 1));
        return account;
    }
}
