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
package org.apache.fineract.commands.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.apache.fineract.commands.domain.CommandWrapper;
import org.junit.jupiter.api.Test;

class CommandWrapperBuilderCutoffTest {

    @Test
    void sourceExactDisbursementHasASeparateCommandIdentity() {
        CommandWrapper nativeCommand = new CommandWrapperBuilder().disburseLoanApplication(42L).build();
        CommandWrapper migrationCommand = new CommandWrapperBuilder().sourceExactDisburseLoanApplication(42L).build();

        assertThat(nativeCommand.actionName()).isEqualTo("DISBURSE");
        assertThat(nativeCommand.getTaskPermissionName()).isEqualTo("DISBURSE_LOAN");
        assertThat(migrationCommand.actionName()).isEqualTo("SOURCEEXACTDISBURSE");
        assertThat(migrationCommand.getTaskPermissionName()).isEqualTo("SOURCEEXACTDISBURSE_LOAN");
    }

    @Test
    void remainingSourceExactLoanLifecycleCommandsHaveSeparatePermissions() {
        assertThat(new CommandWrapperBuilder().sourceExactAdjustTransaction(42L, 7L).build().getTaskPermissionName())
                .isEqualTo("SOURCEEXACTADJUST_LOAN");
        assertThat(new CommandWrapperBuilder().sourceExactUndoLoanApplicationDisbursal(42L).build().getTaskPermissionName())
                .isEqualTo("SOURCEEXACTDISBURSALUNDO_LOAN");
        assertThat(new CommandWrapperBuilder().sourceExactTerminalAdjustment(42L).build().getTaskPermissionName())
                .isEqualTo("SOURCEEXACTTERMINALADJUSTMENT_LOAN");
        assertThat(new CommandWrapperBuilder().sourceExactCreateLoanCharge(42L).build().getTaskPermissionName())
                .isEqualTo("SOURCEEXACTCREATE_LOANCHARGE");
        assertThat(new CommandWrapperBuilder().sourceExactCreateGuarantor(42L).build().getTaskPermissionName())
                .isEqualTo("SOURCEEXACTCREATE_GUARANTOR");
    }
}
