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
package org.apache.fineract.portfolio.savings.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.data.CurrencyData;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.portfolio.savings.SavingsAccountTransactionType;
import org.apache.fineract.portfolio.savings.data.SavingsAccountTransactionData;
import org.apache.fineract.portfolio.savings.data.SavingsAccountTransactionEnumData;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SavingsAccountInterestPostingServiceImplTest {

    private static final String TENANT_IDENTIFIER = "scheduled-interest-preservation-test";

    @BeforeEach
    void setUpTenantRounding() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, TENANT_IDENTIFIER, "Scheduled interest preservation test", "UTC",
                null));
        ThreadLocalContextUtil.setBusinessDates(
                new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 8, 1))));
        MoneyHelper.initializeTenantRoundingMode(TENANT_IDENTIFIER, 6);
    }

    @AfterEach
    void clearTenantRounding() {
        ThreadLocalContextUtil.reset();
        MoneyHelper.clearCacheForTenant(TENANT_IDENTIFIER);
    }

    @Test
    void shouldNotCorrectReferencedManualInterestWhenNativeCalculationDiffers() {
        final SavingsAccountTransactionEnumData type = new SavingsAccountTransactionEnumData(
                SavingsAccountTransactionType.INTEREST_POSTING.getValue().longValue(),
                SavingsAccountTransactionType.INTEREST_POSTING.getCode(), null);
        final CurrencyData currency = new CurrencyData("USD", "US Dollar", 2, 1, "$", "currency.USD");
        final SavingsAccountTransactionData transaction = SavingsAccountTransactionData.createForInterestPosting(1L, type, null, 2L,
                "0002", LocalDate.of(2026, 8, 1), currency, new BigDecimal("4.17"), null, new BigDecimal("104.17"), false,
                LocalDate.of(2026, 8, 1), false, new BigDecimal("104.17"), LocalDate.of(2026, 8, 1), true,
                "AHO_MOVIMIENTOS|1102");

        assertThat(SavingsAccountInterestPostingServiceImpl.requiresInterestCorrection(transaction,
                Money.of(currency, new BigDecimal("4.16")))).isFalse();
    }

    @Test
    void shouldNotUseReferencedImportedTaxForNativeInterestCorrection() {
        final SavingsAccountTransactionEnumData type = new SavingsAccountTransactionEnumData(
                SavingsAccountTransactionType.WITHHOLD_TAX.getValue().longValue(), SavingsAccountTransactionType.WITHHOLD_TAX.getCode(),
                null);
        final CurrencyData currency = new CurrencyData("USD", "US Dollar", 2, 1, "$", "currency.USD");
        final SavingsAccountTransactionData transaction = SavingsAccountTransactionData.createForInterestPosting(1L, type, null, 2L,
                "0002", LocalDate.of(2024, 12, 31), currency, new BigDecimal("8.20"), null, new BigDecimal("100.00"), false,
                LocalDate.of(2024, 12, 31), false, new BigDecimal("100.00"), LocalDate.of(2024, 12, 31), false,
                "MIGT:001:001:0000000084:000000000817");

        assertThat(transaction.isReferencedWithHoldTax()).isTrue();
        assertThat(SavingsAccountInterestPostingServiceImpl.isEligibleWithholdCorrection(transaction)).isFalse();
    }

    @Test
    void shouldKeepMigrationInterestStartWhenItIsLaterThanLastPosting() {
        final LocalDate migrationStart = LocalDate.of(2026, 8, 30);
        final LocalDate lastPosting = LocalDate.of(2025, 12, 31);

        assertThat(SavingsAccountInterestPostingServiceImpl.effectiveInterestCalculationStart(migrationStart, lastPosting))
                .isEqualTo(migrationStart);
    }

    @Test
    void shouldKeepLastPostingWhenItIsLaterThanMigrationInterestStart() {
        final LocalDate migrationStart = LocalDate.of(2026, 8, 30);
        final LocalDate lastPosting = LocalDate.of(2026, 12, 31);

        assertThat(SavingsAccountInterestPostingServiceImpl.effectiveInterestCalculationStart(migrationStart, lastPosting))
                .isEqualTo(lastPosting);
    }
}
