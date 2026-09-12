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
package org.apache.fineract.accounting.provisioning.service;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.util.Optional;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.journalentry.service.JournalEntryWritePlatformService;
import org.apache.fineract.accounting.provisioning.domain.ProvisioningEntry;
import org.apache.fineract.accounting.provisioning.domain.ProvisioningEntryRepository;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ProvisioningEntriesCutoffTest {

    private static final LocalDate HISTORICAL_DATE = LocalDate.of(2026, 9, 30);

    @Mock
    private ProvisioningEntriesReadPlatformService provisioningEntriesReadPlatformService;

    @Mock
    private ProvisioningEntryRepository provisioningEntryRepository;

    @Mock
    private JournalEntryWritePlatformService journalEntryWritePlatformService;

    @Mock
    private AccountingCutoffPolicyService cutoffPolicyService;

    @InjectMocks
    private ProvisioningEntriesWritePlatformServiceJpaRepositoryImpl service;

    @Test
    void operationalMigrationRetainsProvisioningStateButSuppressesItsJournalGroup() {
        ProvisioningEntry entry = mock(ProvisioningEntry.class);
        JsonCommand command = mock(JsonCommand.class);
        when(provisioningEntryRepository.findById(7L)).thenReturn(Optional.of(entry));
        when(entry.getCreatedDate()).thenReturn(HISTORICAL_DATE);
        when(cutoffPolicyService.shouldGenerateAccounting(HISTORICAL_DATE)).thenReturn(false);

        service.createProvisioningJournalEntries(7L, command);

        verify(entry).setIsJournalEntryCreated(Boolean.FALSE);
        verify(provisioningEntryRepository).saveAndFlush(entry);
        verifyNoInteractions(journalEntryWritePlatformService);
    }
}
