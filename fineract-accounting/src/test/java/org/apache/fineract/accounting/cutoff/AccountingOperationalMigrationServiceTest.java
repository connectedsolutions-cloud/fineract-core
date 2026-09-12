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
package org.apache.fineract.accounting.cutoff;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;

class AccountingOperationalMigrationServiceTest {

    @Test
    void scopesAuthorizedMigrationOriginToCommandExecution() {
        PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
        AppUser user = mock(AppUser.class);
        AccountingPostingContext postingContext = new AccountingPostingContext();
        AccountingOperationalMigrationService service = new AccountingOperationalMigrationService(securityContext, postingContext);
        when(securityContext.authenticatedUser()).thenReturn(user);

        AccountingPostingOrigin observed = service.execute(postingContext::getOrigin);

        assertThat(observed).isEqualTo(AccountingPostingOrigin.ARISSTO_OPERATIONAL_MIGRATION);
        assertThat(postingContext.getOrigin()).isEqualTo(AccountingPostingOrigin.NATIVE_OPERATION);
        verify(user).validateHasPermissionTo(AccountingOperationalMigrationService.PERMISSION);
    }
}
