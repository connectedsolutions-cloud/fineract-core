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
package org.apache.fineract.useradministration.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.Set;
import org.apache.fineract.organisation.office.domain.Office;
import org.junit.jupiter.api.Test;

class AppUserTest {

    @Test
    void officeAccessUsesPersistentIdentityAcrossEntityInstances() {
        Office assignedOffice = mock(Office.class);
        Office reloadedOffice = mock(Office.class);
        when(assignedOffice.getId()).thenReturn(7L);
        when(reloadedOffice.getId()).thenReturn(7L);

        AppUser user = new AppUser();
        user.setOffices(Set.of(assignedOffice));

        assertThat(user.hasAccessToOffice(reloadedOffice)).isTrue();
    }
}
