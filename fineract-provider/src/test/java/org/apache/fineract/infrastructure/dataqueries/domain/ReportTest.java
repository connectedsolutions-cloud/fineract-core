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
package org.apache.fineract.infrastructure.dataqueries.domain;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.junit.jupiter.api.Test;

class ReportTest {

    private static final List<String> REPORT_TYPES = List.of("Table", "Chart", "Pentaho");

    @Test
    void tableReportAllowsNoSubType() {
        assertDoesNotThrow(() -> report("Table", null));
    }

    @Test
    void tableReportAllowsVisualRendererSubType() {
        assertDoesNotThrow(() -> report("Table", "VisualVoucher"));
        assertDoesNotThrow(() -> report("Table", "VisualBranchVoucher"));
    }

    @Test
    void tableReportRejectsNonVisualSubType() {
        assertThrows(PlatformApiDataValidationException.class, () -> report("Table", "Voucher"));
    }

    @Test
    void nonTableReportRejectsVisualSubType() {
        assertThrows(PlatformApiDataValidationException.class, () -> report("Pentaho", "VisualVoucher"));
    }

    private Report report(final String type, final String subType) {
        return new Report("Test Report", type, subType, "Accounting", "Test report", true, "select 1", REPORT_TYPES);
    }
}
