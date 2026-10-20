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
package org.apache.fineract.portfolio.delinquency.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.delinquency.validator.DelinquencyRangeParseAndValidator;
import org.junit.jupiter.api.Test;

class DelinquencyRangeZeroDaysValidatorTest {

    private final DelinquencyRangeParseAndValidator validator = new DelinquencyRangeParseAndValidator(new FromJsonHelper());

    @Test
    void acceptsZeroAsMinimumAge() {
        var range = validator.validateAndParseUpdate(command(0));
        assertEquals(0, range.getMinimumAgeDays());
    }

    @Test
    void rejectsNegativeMinimumAge() {
        assertThrows(PlatformApiDataValidationException.class, () -> validator.validateAndParseUpdate(command(-1)));
    }

    private static JsonCommand command(int minimumAge) {
        String json = "{\"classification\":\"A1\",\"minimumAgeDays\":" + minimumAge + ",\"maximumAgeDays\":7,\"locale\":\"en\"}";
        JsonCommand command = mock(JsonCommand.class);
        when(command.json()).thenReturn(json);
        return command;
    }
}
