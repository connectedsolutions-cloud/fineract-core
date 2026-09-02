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
package org.apache.fineract.portfolio.namingsequence;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class CredesalNamingCodesTest {

    @Test
    void extractsPartyPrefixFromTenDigitAffiliation() {
        assertEquals("00658", CredesalNamingCodes.extractPartyPrefix("0000000658").orElseThrow());
    }

    @Test
    void rejectsNonNumericOrWrongLengthAffiliation() {
        assertTrue(CredesalNamingCodes.extractPartyPrefix("ABC").isEmpty());
        assertTrue(CredesalNamingCodes.extractPartyPrefix("12345").isEmpty());
        assertTrue(CredesalNamingCodes.extractPartyPrefix(null).isEmpty());
    }

    @Test
    void formatsSpecExamplesForAffiliation0000000658() {
        final String party = "00658";
        assertEquals("006583M101", CredesalNamingCodes.formatValue(CredesalNamingCodes.composePrefix(party, "3M1"), 1, 2));
        assertEquals("006584V101", CredesalNamingCodes.formatValue(CredesalNamingCodes.composePrefix(party, "4V1"), 1, 2));
        assertEquals("006585D301", CredesalNamingCodes.formatValue(CredesalNamingCodes.composePrefix(party, "5D3"), 1, 2));
        assertEquals("006581AC01", CredesalNamingCodes.formatValue(CredesalNamingCodes.composePrefix(party, "1AC"), 1, 2));
        assertEquals("006581AP01", CredesalNamingCodes.formatValue(CredesalNamingCodes.composePrefix(party, "1AP"), 1, 2));
        assertEquals("001", CredesalNamingCodes.formatValue("", 1, 3));
    }

    @Test
    void acceptsApprovedProductCodes() {
        assertTrue(CredesalNamingCodes.isValid(CredesalNamingNamespace.LOAN, "3M1"));
        assertTrue(CredesalNamingCodes.isValid(CredesalNamingNamespace.SAVINGS, "4V1"));
        assertTrue(CredesalNamingCodes.isValid(CredesalNamingNamespace.SAVINGS, "5D3"));
        assertTrue(CredesalNamingCodes.isValid(CredesalNamingNamespace.SHARE_CERTIFICATE, "1AC"));
        assertTrue(CredesalNamingCodes.isValid(CredesalNamingNamespace.SHARE_CERTIFICATE, "1AP"));
    }

    @Test
    void rejectsDisabledDpfCodes() {
        assertFalse(CredesalNamingCodes.isValid(CredesalNamingNamespace.SAVINGS, "5D4"));
        assertFalse(CredesalNamingCodes.isValid(CredesalNamingNamespace.SAVINGS, "5D5"));
        assertNotNull(CredesalNamingCodes.validationError(CredesalNamingNamespace.SAVINGS, "5D4"));
        assertNotNull(CredesalNamingCodes.validationError(CredesalNamingNamespace.SAVINGS, "5D5"));
    }
}
