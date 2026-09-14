/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information regarding copyright ownership. The ASF licenses this file to you under
 * the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain
 * a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS"
 * BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language
 * governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.savingsaccountparty.service;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.util.List;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.client.domain.ClientRepository;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepositoryWrapper;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryRequest;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsAuthorizedPersonRepository;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiaryRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SavingsAccountPartyServiceImplTest {

    private SavingsAccountRepositoryWrapper savingsAccountRepository;
    private SavingsBeneficiaryRepository beneficiaryRepository;
    private SavingsAuthorizedPersonRepository authorizedPersonRepository;
    private ClientRepository clientRepository;
    private SavingsAccountPartyServiceImpl service;

    @BeforeEach
    void setUp() {
        savingsAccountRepository = mock(SavingsAccountRepositoryWrapper.class);
        beneficiaryRepository = mock(SavingsBeneficiaryRepository.class);
        authorizedPersonRepository = mock(SavingsAuthorizedPersonRepository.class);
        clientRepository = mock(ClientRepository.class);
        service = new SavingsAccountPartyServiceImpl(savingsAccountRepository, beneficiaryRepository, authorizedPersonRepository,
                clientRepository);
        when(savingsAccountRepository.findOneWithNotFoundDetection(17L)).thenReturn(mock(SavingsAccount.class));
    }

    @Test
    void shouldRejectBeneficiaryAllocationsThatDoNotTotalOneHundred() {
        final SavingsBeneficiaryRequest first = beneficiary("First", "60.00");
        final SavingsBeneficiaryRequest second = beneficiary("Second", "30.00");

        assertThatThrownBy(() -> service.replaceBeneficiaries(17L, List.of(first, second)))
                .isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("must total exactly 100.00");
        verifyNoInteractions(beneficiaryRepository, authorizedPersonRepository, clientRepository);
    }

    @Test
    void shouldRejectMissingOrNonPositiveAllocation() {
        final SavingsBeneficiaryRequest beneficiary = beneficiary("First", "0.00");

        assertThatThrownBy(() -> service.replaceBeneficiaries(17L, List.of(beneficiary)))
                .isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("greater than zero");
        verifyNoInteractions(beneficiaryRepository, authorizedPersonRepository, clientRepository);
    }

    private SavingsBeneficiaryRequest beneficiary(final String name, final String percentage) {
        final SavingsBeneficiaryRequest request = new SavingsBeneficiaryRequest();
        request.setGivenName(name);
        request.setAllocationPercentage(new BigDecimal(percentage));
        return request;
    }
}
