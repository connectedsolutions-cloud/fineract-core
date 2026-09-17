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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.portfolio.client.domain.ClientRepository;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepositoryWrapper;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryRequest;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsAuthorizedPersonRepository;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiary;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiaryRepository;
import org.junit.jupiter.api.AfterEach;
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
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "UTC", null));
        savingsAccountRepository = mock(SavingsAccountRepositoryWrapper.class);
        beneficiaryRepository = mock(SavingsBeneficiaryRepository.class);
        authorizedPersonRepository = mock(SavingsAuthorizedPersonRepository.class);
        clientRepository = mock(ClientRepository.class);
        service = new SavingsAccountPartyServiceImpl(savingsAccountRepository, beneficiaryRepository, authorizedPersonRepository,
                clientRepository);
        when(savingsAccountRepository.findOneWithNotFoundDetection(17L)).thenReturn(mock(SavingsAccount.class));
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
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

    @Test
    void shouldRetainNewBeneficiaryAfterReplacement() {
        final SavingsBeneficiaryRequest request = beneficiary("First", "100.00");
        request.setExternalId("beneficiary-1");
        final SavingsAccount account = savingsAccountRepository.findOneWithNotFoundDetection(17L);
        when(account.getId()).thenReturn(17L);
        when(beneficiaryRepository.findByExternalId("beneficiary-1")).thenReturn(Optional.empty());
        final AtomicReference<SavingsBeneficiary> persisted = new AtomicReference<>();
        when(beneficiaryRepository.saveAndFlush(any(SavingsBeneficiary.class))).thenAnswer(invocation -> {
            final SavingsBeneficiary saved = invocation.getArgument(0);
            saved.setId(99L);
            persisted.set(saved);
            return saved;
        });
        when(beneficiaryRepository.findBySavingsAccountIdAndActiveTrueOrderById(17L))
                .thenAnswer(invocation -> persisted.get() == null ? List.of() : List.of(persisted.get()));

        final var result = service.replaceBeneficiaries(17L, List.of(request));

        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getExternalId()).isEqualTo("beneficiary-1");
    }

    private SavingsBeneficiaryRequest beneficiary(final String name, final String percentage) {
        final SavingsBeneficiaryRequest request = new SavingsBeneficiaryRequest();
        request.setGivenName(name);
        request.setAllocationPercentage(new BigDecimal(percentage));
        return request;
    }
}
