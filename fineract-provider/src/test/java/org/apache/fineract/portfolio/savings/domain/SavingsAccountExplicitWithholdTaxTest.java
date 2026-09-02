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
import static org.mockito.Mockito.mock;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.apache.fineract.portfolio.savings.SavingsAccountTransactionType;
import org.apache.fineract.portfolio.savings.exception.SavingsExplicitWithholdTaxException;
import org.apache.fineract.portfolio.tax.domain.TaxComponent;
import org.apache.fineract.portfolio.tax.domain.TaxGroup;
import org.apache.fineract.portfolio.tax.domain.TaxGroupMappings;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class SavingsAccountExplicitWithholdTaxTest {

    private static final LocalDate TRANSACTION_DATE = LocalDate.of(2025, 8, 25);
    private static final String SOURCE_REFERENCE = "arissto:dpf-interest:123";
    private static final String TENANT_IDENTIFIER = "explicit-tax-test";

    @BeforeEach
    void setUpTenantRounding() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, TENANT_IDENTIFIER, "Explicit tax test", "UTC", null));
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, TRANSACTION_DATE)));
        MoneyHelper.initializeTenantRoundingMode(TENANT_IDENTIFIER, 6);
    }

    @AfterEach
    void clearTenantRounding() {
        ThreadLocalContextUtil.reset();
        MoneyHelper.clearCacheForTenant(TENANT_IDENTIFIER);
    }

    @Test
    void shouldCreateNativeWithholdTaxTransactionUsingConfiguredTaxGroup() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT, tenPercentTaxGroup());

        final SavingsAccountTransaction transaction = account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"),
                new BigDecimal("10.00"), TRANSACTION_DATE, SOURCE_REFERENCE, false);

        assertThat(transaction.getTransactionType()).isEqualTo(SavingsAccountTransactionType.WITHHOLD_TAX);
        assertThat(transaction.getAmount()).isEqualByComparingTo("10.00");
        assertThat(transaction.getRefNo()).isEqualTo(SOURCE_REFERENCE);
        assertThat(transaction.getTaxDetails()).singleElement().satisfies(detail -> {
            assertThat(detail.getAmount()).isEqualByComparingTo("10.00");
            assertThat(detail.getTaxComponent().getPercentage()).isEqualByComparingTo("10.00");
        });
        assertThat(account.getTransactions()).containsExactly(transaction);
    }

    @Test
    void shouldAcceptSourceTaxAmountWithinOneCurrencyRoundingUnit() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT, tenPercentTaxGroup());

        final SavingsAccountTransaction transaction = account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"),
                new BigDecimal("9.99"), TRANSACTION_DATE, SOURCE_REFERENCE, false);

        assertThat(transaction.getAmount()).isEqualByComparingTo("9.99");
        assertThat(transaction.getTaxDetails()).singleElement()
                .satisfies(detail -> assertThat(detail.getAmount()).isEqualByComparingTo("9.99"));
    }

    @Test
    void shouldRejectSourceTaxAmountOutsideOneCurrencyRoundingUnit() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT, tenPercentTaxGroup());

        assertThatThrownBy(() -> account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"), new BigDecimal("9.98"),
                TRANSACTION_DATE, SOURCE_REFERENCE, false)).isInstanceOf(SavingsExplicitWithholdTaxException.class)
                .hasMessageContaining("amount.mismatch");

        assertThat(account.getTransactions()).isEmpty();
    }

    @Test
    void shouldRequireTaxConfigurationWithoutEnablingAutomaticWithholding() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT, null);

        assertThat(account.withHoldTax()).isFalse();
        assertThatThrownBy(() -> account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"), new BigDecimal("10.00"),
                TRANSACTION_DATE, SOURCE_REFERENCE, false)).isInstanceOf(SavingsExplicitWithholdTaxException.class)
                .hasMessageContaining("tax.group.missing");
    }

    @Test
    void shouldRetainTaxGroupOnProductUpdatesWhenAutomaticWithholdingIsDisabled() {
        final SavingsProduct product = new SavingsProduct();
        final TaxGroup taxGroup = tenPercentTaxGroup();
        ReflectionTestUtils.setField(product, "taxGroup", taxGroup);
        ReflectionTestUtils.setField(product, "withHoldTax", false);
        ReflectionTestUtils.setField(product, "currency", new MonetaryCurrency("USD", 2, 1));

        product.update(mock(JsonCommand.class));

        assertThat(product.withHoldTax()).isFalse();
        assertThat(product.getTaxGroup()).isSameAs(taxGroup);
    }

    @Test
    void shouldOnlyPostExplicitTaxToOrdinarySavingsAccount() {
        final SavingsAccount account = savingsAccount(DepositAccountType.FIXED_DEPOSIT, tenPercentTaxGroup());

        assertThatThrownBy(() -> account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"), new BigDecimal("10.00"),
                TRANSACTION_DATE, SOURCE_REFERENCE, false)).isInstanceOf(SavingsExplicitWithholdTaxException.class)
                .hasMessageContaining("linked.account.must.be.ordinary.savings");
    }

    @Test
    void shouldPreserveNativeTaxDetailsAndReferenceOnReversal() {
        final SavingsAccount account = savingsAccount(DepositAccountType.SAVINGS_DEPOSIT, tenPercentTaxGroup());
        final SavingsAccountTransaction original = account.createExplicitWithholdTaxTransaction(new BigDecimal("100.00"),
                new BigDecimal("10.00"), TRANSACTION_DATE, SOURCE_REFERENCE, false);

        final SavingsAccountTransaction reversal = SavingsAccountTransaction.reversal(original);

        assertThat(reversal.getTransactionType()).isEqualTo(SavingsAccountTransactionType.WITHHOLD_TAX);
        assertThat(reversal.getRefNo()).isEqualTo(SOURCE_REFERENCE);
        assertThat(reversal.getTaxDetails()).singleElement().satisfies(detail -> {
            assertThat(detail.getAmount()).isEqualByComparingTo("10.00");
            assertThat(detail.getSavingsAccountTransaction()).isSameAs(reversal);
        });
    }

    private SavingsAccount savingsAccount(final DepositAccountType depositAccountType, final TaxGroup taxGroup) {
        final SavingsAccount account = new SavingsAccount();
        ReflectionTestUtils.setField(account, "depositType", depositAccountType.getValue());
        ReflectionTestUtils.setField(account, "currency", new MonetaryCurrency("USD", 2, 1));
        ReflectionTestUtils.setField(account, "taxGroup", taxGroup);
        ReflectionTestUtils.setField(account, "withHoldTax", false);
        return account;
    }

    private TaxGroup tenPercentTaxGroup() {
        final TaxComponent component = TaxComponent.createTaxComponent("ISR", new BigDecimal("10.00"), null, null, null, null,
                LocalDate.of(2000, 1, 1));
        final TaxGroupMappings mapping = TaxGroupMappings.createTaxGroupMappings(component, LocalDate.of(2000, 1, 1));
        return TaxGroup.createTaxGroup("Arissto ISR", Set.of(mapping));
    }
}
