/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;

import java.math.BigDecimal;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class ShareYieldCalculatorTest {

    @Test
    void calculatesActualActualDailyAccrualAtSourcePrecision() {
        assertThat(ShareYieldCalculator.dailyAccrual(new BigDecimal("1125.00"), new BigDecimal("7.00"), 365))
                .isEqualByComparingTo("0.21575342");
    }

    @Test
    void usesLeapYearBasis() {
        assertThat(ShareYieldCalculator.actualYearBasis(LocalDate.of(2024, 2, 29))).isEqualTo(366);
        assertThat(ShareYieldCalculator.actualYearBasis(LocalDate.of(2025, 2, 28))).isEqualTo(365);
    }

    @Test
    void rejectsUnsupportedDayCountBasis() {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ShareYieldCalculator.dailyAccrual(BigDecimal.ONE, BigDecimal.ONE, 360));
    }
}
