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
package org.apache.fineract.portfolio.transfer.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Field;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientRepositoryWrapper;
import org.apache.fineract.portfolio.client.domain.ClientTransferDetails;
import org.apache.fineract.portfolio.client.domain.ClientTransferDetailsRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.service.LoanWritePlatformService;
import org.apache.fineract.portfolio.note.service.NoteWritePlatformService;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepositoryWrapper;
import org.apache.fineract.portfolio.transfer.data.TransfersDataValidator;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockedStatic;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class TransferWritePlatformServiceJpaRepositoryImplTest {

    @Mock
    private ClientRepositoryWrapper clientRepositoryWrapper;
    @Mock
    private LoanRepositoryWrapper loanRepositoryWrapper;
    @Mock
    private SavingsAccountRepositoryWrapper savingsAccountRepositoryWrapper;
    @Mock
    private LoanWritePlatformService loanWritePlatformService;
    @Mock
    private TransfersDataValidator transfersDataValidator;
    @Mock
    private NoteWritePlatformService noteWritePlatformService;
    @Mock
    private ClientTransferDetailsRepositoryWrapper clientTransferDetailsRepositoryWrapper;
    @Mock
    private PlatformSecurityContext context;
    @InjectMocks
    private TransferWritePlatformServiceJpaRepositoryImpl service;

    @Test
    void acceptanceKeepsProposedDateAndOriginalOfficeInNativeHistory() throws Exception {
        final long clientId = 157L;
        final LocalDate effectiveDate = LocalDate.of(2024, 11, 27);
        final Client client = mock(Client.class);
        final Office fromOffice = mock(Office.class);
        final Office toOffice = mock(Office.class);
        final Loan activeLoan = mock(Loan.class);
        final AppUser user = mock(AppUser.class);
        final JsonCommand command = mock(JsonCommand.class);

        when(clientRepositoryWrapper.findOneWithNotFoundDetection(clientId, true)).thenReturn(client);
        when(client.isTransferInProgress()).thenReturn(true);
        when(client.getId()).thenReturn(clientId);
        when(client.getOffice()).thenReturn(fromOffice);
        when(client.getTransferToOffice()).thenReturn(toOffice);
        when(client.getProposedTransferDate()).thenReturn(effectiveDate);
        when(client.getGroups()).thenReturn(Set.of());
        when(loanRepositoryWrapper.doNonClosedLoanAccountsExistForClient(clientId)).thenReturn(true);
        when(loanRepositoryWrapper.findLoanByClientId(clientId)).thenReturn(List.of(activeLoan));
        when(activeLoan.isDisbursed()).thenReturn(true);
        when(activeLoan.isClosed()).thenReturn(false);
        when(fromOffice.getId()).thenReturn(1L);
        when(toOffice.getId()).thenReturn(2L);
        when(context.authenticatedUser()).thenReturn(user);
        when(user.getId()).thenReturn(7L);
        when(command.longValueOfParameterNamed("staffId")).thenReturn(null);
        when(command.longValueOfParameterNamed("destinationGroupId")).thenReturn(null);

        try (MockedStatic<DateUtils> dates = mockStatic(DateUtils.class)) {
            dates.when(DateUtils::getBusinessLocalDate).thenReturn(LocalDate.of(2026, 10, 9));
            service.acceptClientTransfer(clientId, command);
        }

        verify(loanWritePlatformService).acceptLoanTransfer(activeLoan, effectiveDate, toOffice, null);
        verify(client).updateOfficeJoiningDate(effectiveDate);
        verify(client).updateOffice(toOffice);
        final ArgumentCaptor<ClientTransferDetails> saved = ArgumentCaptor.forClass(ClientTransferDetails.class);
        verify(clientTransferDetailsRepositoryWrapper).save(saved.capture());
        assertThat(field(saved.getValue(), "fromOfficeId")).isEqualTo(1L);
        assertThat(field(saved.getValue(), "toOfficeId")).isEqualTo(2L);
        assertThat(field(saved.getValue(), "proposedTransferDate")).isEqualTo(effectiveDate);
        assertThat(field(saved.getValue(), "transferEventType")).isEqualTo(TransferEventType.ACCEPTANCE.getValue());
    }

    private static Object field(final Object object, final String name) throws ReflectiveOperationException {
        final Field field = object.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(object);
    }
}
