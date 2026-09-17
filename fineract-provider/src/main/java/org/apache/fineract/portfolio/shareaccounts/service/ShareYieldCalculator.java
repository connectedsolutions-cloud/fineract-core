/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;

public final class ShareYieldCalculator {

    private ShareYieldCalculator() {}

    public static int actualYearBasis(LocalDate date) {
        return date.isLeapYear() ? 366 : 365;
    }

    public static BigDecimal dailyAccrual(BigDecimal baseAmount, BigDecimal annualRate, int dayCountBasis) {
        if (dayCountBasis != 365 && dayCountBasis != 366) {
            throw new IllegalArgumentException("dayCountBasis must be 365 or 366");
        }
        return baseAmount.multiply(annualRate).divide(BigDecimal.valueOf(100L * dayCountBasis), 8, RoundingMode.HALF_UP);
    }
}
