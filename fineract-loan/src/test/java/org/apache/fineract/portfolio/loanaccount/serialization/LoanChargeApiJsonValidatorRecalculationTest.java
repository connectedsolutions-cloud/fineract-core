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

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.gson.JsonParser;
import java.util.ArrayList;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.DataValidatorBuilder;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.charge.domain.Charge;
import org.apache.fineract.portfolio.charge.domain.ChargeRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargeRepository;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;
import org.junit.jupiter.api.Test;

class LoanChargeApiJsonValidatorRecalculationTest {

    @Test
    void acceptsOpeningOutstandingPrincipalInsuranceWithRecalculation() {
        assertTrue(validateInstallmentCharge(8, true).isEmpty());
    }

    @Test
    void preservesRestrictionForPercentageOfDisbursedPrincipal() {
        assertFalse(validateInstallmentCharge(2, true).isEmpty());
    }

    @Test
    void preservesRestrictionForPercentageOfPrincipalAndInterest() {
        assertFalse(validateInstallmentCharge(3, true).isEmpty());
    }

    @Test
    void acceptsLegacyProductWithoutRecalculation() {
        assertTrue(validateInstallmentCharge(2, false).isEmpty());
    }

    private ArrayList<ApiParameterError> validateInstallmentCharge(int calculationType, boolean recalculation) {
        final ChargeRepositoryWrapper charges = mock(ChargeRepositoryWrapper.class);
        final Charge definition = mock(Charge.class);
        when(charges.findOneWithNotFoundDetection(1L)).thenReturn(definition);
        when(definition.getCurrencyCode()).thenReturn("USD");
        final LoanProduct product = mock(LoanProduct.class);
        when(product.hasCurrencyCodeOf("USD")).thenReturn(true);
        when(product.isInterestRecalculationEnabled()).thenReturn(recalculation);
        final LoanChargeApiJsonValidator validator = new LoanChargeApiJsonValidator(new FromJsonHelper(), charges,
                mock(LoanChargeRepository.class));
        final ArrayList<ApiParameterError> errors = new ArrayList<>();
        validator.validateLoanCharges(JsonParser.parseString("""
                {"locale":"en","charges":[{"chargeId":1,"amount":0.06,
                "chargeTimeType":8,"chargeCalculationType":%d,"chargePaymentMode":0}]}
                """.formatted(calculationType)), product, new DataValidatorBuilder(errors).resource("loan"));
        return errors;
    }
}
