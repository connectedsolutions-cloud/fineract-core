/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.portfolio.savings.data;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.junit.jupiter.api.Test;

class DepositAccountDataValidatorSourceExactUnfundedTest {

    private final DepositAccountDataValidator validator = new DepositAccountDataValidator(new FromJsonHelper(),
            mock(DepositProductDataValidator.class));

    @Test
    void sourceExactUnfundedCreationAllowsExactlyZeroDepositAmount() {
        assertDoesNotThrow(() -> validator.validateSourceExactUnfundedFixedDepositForSubmit(request("0.00")));
    }

    @Test
    void sourceExactUnfundedCreationRejectsPositiveDepositAmount() {
        final PlatformApiDataValidationException exception = assertThrows(PlatformApiDataValidationException.class,
                () -> validator.validateSourceExactUnfundedFixedDepositForSubmit(request("1.00")));

        assertThat(exception.getErrors()).anySatisfy(error -> assertThat(error.getUserMessageGlobalisationCode())
                .endsWith("depositAmount.must.be.zero.for.source.exact.unfunded"));
    }

    @Test
    void ordinaryCreationStillRejectsZeroDepositAmount() {
        final PlatformApiDataValidationException exception = assertThrows(PlatformApiDataValidationException.class,
                () -> validator.validateFixedDepositForSubmit(request("0.00")));

        assertThat(exception.getErrors()).anySatisfy(
                error -> assertThat(error.getUserMessageGlobalisationCode()).endsWith("depositAmount.not.greater.than.zero"));
    }

    private String request(final String depositAmount) {
        return """
                {
                  "clientId": 42,
                  "productId": 5,
                  "submittedOnDate": "2026-06-13",
                  "dateFormat": "yyyy-MM-dd",
                  "locale": "en",
                  "depositAmount": "%s",
                  "depositPeriod": 90,
                  "depositPeriodFrequencyId": 0
                }
                """.formatted(depositAmount);
    }
}
