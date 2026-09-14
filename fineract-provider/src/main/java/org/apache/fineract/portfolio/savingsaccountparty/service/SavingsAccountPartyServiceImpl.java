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

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientRepository;
import org.apache.fineract.portfolio.client.exception.ClientNotFoundException;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepositoryWrapper;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonRequest;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryRequest;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsAuthorizedPerson;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsAuthorizedPersonRepository;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiary;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiaryRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class SavingsAccountPartyServiceImpl implements SavingsAccountPartyService {

    private static final BigDecimal FULL_ALLOCATION = new BigDecimal("100.00");
    private final SavingsAccountRepositoryWrapper savingsAccountRepository;
    private final SavingsBeneficiaryRepository beneficiaryRepository;
    private final SavingsAuthorizedPersonRepository authorizedPersonRepository;
    private final ClientRepository clientRepository;

    @Override
    @Transactional(readOnly = true)
    public List<SavingsBeneficiaryData> retrieveBeneficiaries(final Long accountId) {
        loadAccount(accountId);
        return beneficiaryRepository.findBySavingsAccountIdAndActiveTrueOrderById(accountId).stream().map(SavingsBeneficiaryData::from).toList();
    }

    @Override
    @Transactional
    public List<SavingsBeneficiaryData> replaceBeneficiaries(final Long accountId, final List<SavingsBeneficiaryRequest> requests) {
        final SavingsAccount account = loadAccount(accountId);
        final List<SavingsBeneficiaryRequest> desired = requests == null ? List.of() : requests;
        validateBeneficiaries(desired);

        final Set<Long> retainedIds = new HashSet<>();
        for (final SavingsBeneficiaryRequest request : desired) {
            final SavingsBeneficiary beneficiary = resolveBeneficiary(accountId, request);
            beneficiary.setSavingsAccount(account);
            beneficiary.setLinkedClient(loadOptionalClient(request.getLinkedClientId()));
            beneficiary.setExternalId(trim(request.getExternalId()));
            beneficiary.setGivenName(requiredName(request.getGivenName()));
            beneficiary.setSurname(trim(request.getSurname()));
            beneficiary.setAllocationPercentage(request.getAllocationPercentage());
            beneficiary.setDateOfBirth(request.getDateOfBirth());
            beneficiary.setSourceAge(trim(request.getSourceAge()));
            beneficiary.setDui(trim(request.getDui()));
            beneficiary.setRelationship(trim(request.getRelationship()));
            beneficiary.setAddress(trim(request.getAddress()));
            beneficiary.setPhone(trim(request.getPhone()));
            beneficiary.setCommunicateDesignation(request.getCommunicateDesignation());
            beneficiary.setSourceHash(trim(request.getSourceHash()));
            beneficiary.setActive(true);
            touch(beneficiary);
            final SavingsBeneficiary saved = beneficiaryRepository.save(beneficiary);
            retainedIds.add(saved.getId());
        }

        for (final SavingsBeneficiary existing : beneficiaryRepository.findBySavingsAccountIdAndActiveTrueOrderById(accountId)) {
            if (!retainedIds.contains(existing.getId())) {
                existing.setActive(false);
                existing.setUpdatedAt(DateUtils.getLocalDateTimeOfTenant());
                beneficiaryRepository.save(existing);
            }
        }
        beneficiaryRepository.flush();
        return retrieveBeneficiaries(accountId);
    }

    @Override
    @Transactional(readOnly = true)
    public List<SavingsAuthorizedPersonData> retrieveAuthorizedPersons(final Long accountId) {
        loadAccount(accountId);
        return authorizedPersonRepository.findBySavingsAccountIdAndActiveTrueOrderById(accountId).stream()
                .map(SavingsAuthorizedPersonData::from).toList();
    }

    @Override
    @Transactional
    public List<SavingsAuthorizedPersonData> replaceAuthorizedPersons(final Long accountId,
            final List<SavingsAuthorizedPersonRequest> requests) {
        final SavingsAccount account = loadAccount(accountId);
        final List<SavingsAuthorizedPersonRequest> desired = requests == null ? List.of() : requests;
        final Set<Long> retainedIds = new HashSet<>();
        final Set<String> externalIds = new HashSet<>();
        for (final SavingsAuthorizedPersonRequest request : desired) {
            if (request == null) {
                throw invalid("error.msg.savings.account.party.request.required", "Authorized person details are required");
            }
            final String externalId = trim(request.getExternalId());
            if (externalId != null && !externalIds.add(externalId)) {
                throw invalid("error.msg.savings.account.authorized.person.external.id.duplicate",
                        "An authorized person external ID cannot appear twice");
            }
            final SavingsAuthorizedPerson person = resolveAuthorizedPerson(accountId, request);
            final SavingsAuthorizedPersonData saved = saveAuthorizedPerson(account, person, request);
            retainedIds.add(saved.getId());
        }
        for (final SavingsAuthorizedPerson existing : authorizedPersonRepository
                .findBySavingsAccountIdAndActiveTrueOrderById(accountId)) {
            if (!retainedIds.contains(existing.getId())) {
                existing.setActive(false);
                existing.setUpdatedAt(DateUtils.getLocalDateTimeOfTenant());
                authorizedPersonRepository.save(existing);
            }
        }
        authorizedPersonRepository.flush();
        return retrieveAuthorizedPersons(accountId);
    }

    @Override
    @Transactional
    public SavingsAuthorizedPersonData createAuthorizedPerson(final Long accountId, final SavingsAuthorizedPersonRequest request) {
        return saveAuthorizedPerson(loadAccount(accountId), new SavingsAuthorizedPerson(), request);
    }

    @Override
    @Transactional
    public SavingsAuthorizedPersonData updateAuthorizedPerson(final Long accountId, final Long personId,
            final SavingsAuthorizedPersonRequest request) {
        loadAccount(accountId);
        final SavingsAuthorizedPerson person = authorizedPersonRepository.findById(personId)
                .orElseThrow(() -> notFound("authorized.person", personId));
        assertAccount(accountId, person.getSavingsAccount().getId());
        return saveAuthorizedPerson(person.getSavingsAccount(), person, request);
    }

    @Override
    @Transactional
    public void deleteAuthorizedPerson(final Long accountId, final Long personId) {
        loadAccount(accountId);
        final SavingsAuthorizedPerson person = authorizedPersonRepository.findById(personId)
                .orElseThrow(() -> notFound("authorized.person", personId));
        assertAccount(accountId, person.getSavingsAccount().getId());
        person.setActive(false);
        person.setUpdatedAt(DateUtils.getLocalDateTimeOfTenant());
        authorizedPersonRepository.saveAndFlush(person);
    }

    private SavingsAuthorizedPersonData saveAuthorizedPerson(final SavingsAccount account, final SavingsAuthorizedPerson person,
            final SavingsAuthorizedPersonRequest request) {
        if (request == null) {
            throw invalid("error.msg.savings.account.party.request.required", "Authorized person details are required");
        }
        final String externalId = trim(request.getExternalId());
        if (externalId != null) {
            authorizedPersonRepository.findByExternalId(externalId).filter(existing -> !existing.getId().equals(person.getId()))
                    .ifPresent(existing -> {
                        throw invalid("error.msg.savings.account.authorized.person.external.id.duplicate",
                                "Authorized person external ID is already in use");
                    });
        }
        person.setSavingsAccount(account);
        person.setLinkedClient(loadOptionalClient(request.getLinkedClientId()));
        person.setExternalId(externalId);
        person.setGivenName(requiredName(request.getGivenName()));
        person.setSurname(trim(request.getSurname()));
        person.setDateOfBirth(request.getDateOfBirth());
        person.setDui(trim(request.getDui()));
        person.setRelationship(trim(request.getRelationship()));
        person.setAddress(trim(request.getAddress()));
        person.setPhone(trim(request.getPhone()));
        person.setPrintOnContract(request.getPrintOnContract());
        person.setPrintOnPassbook(request.getPrintOnPassbook());
        person.setSignatureReference(trim(request.getSignatureReference()));
        person.setSourceHash(trim(request.getSourceHash()));
        person.setActive(true);
        touch(person);
        return SavingsAuthorizedPersonData.from(authorizedPersonRepository.saveAndFlush(person));
    }

    private SavingsAuthorizedPerson resolveAuthorizedPerson(final Long accountId, final SavingsAuthorizedPersonRequest request) {
        SavingsAuthorizedPerson person = null;
        if (request.getId() != null) {
            person = authorizedPersonRepository.findById(request.getId())
                    .orElseThrow(() -> notFound("authorized.person", request.getId()));
        } else if (StringUtils.isNotBlank(request.getExternalId())) {
            person = authorizedPersonRepository.findByExternalId(request.getExternalId().trim()).orElse(null);
        }
        if (person == null) {
            person = new SavingsAuthorizedPerson();
        } else {
            assertAccount(accountId, person.getSavingsAccount().getId());
        }
        return person;
    }

    private void validateBeneficiaries(final List<SavingsBeneficiaryRequest> requests) {
        final Set<Long> ids = new HashSet<>();
        final Set<String> externalIds = new HashSet<>();
        BigDecimal total = BigDecimal.ZERO;
        for (final SavingsBeneficiaryRequest request : requests) {
            if (request == null || request.getAllocationPercentage() == null || request.getAllocationPercentage().signum() <= 0
                    || request.getAllocationPercentage().compareTo(FULL_ALLOCATION) > 0) {
                throw invalid("error.msg.savings.beneficiary.percentage.invalid",
                        "Every beneficiary requires an allocation percentage greater than zero and no more than 100");
            }
            requiredName(request.getGivenName());
            if (request.getId() != null && !ids.add(request.getId())) {
                throw invalid("error.msg.savings.beneficiary.id.duplicate", "A beneficiary cannot appear twice in one replacement request");
            }
            final String externalId = trim(request.getExternalId());
            if (externalId != null && !externalIds.add(externalId)) {
                throw invalid("error.msg.savings.beneficiary.external.id.duplicate", "A beneficiary external ID cannot appear twice");
            }
            total = total.add(request.getAllocationPercentage());
        }
        if (!requests.isEmpty() && total.compareTo(FULL_ALLOCATION) != 0) {
            throw invalid("error.msg.savings.beneficiary.percentage.total.invalid",
                    "Active beneficiary allocation percentages must total exactly 100.00");
        }
    }

    private SavingsBeneficiary resolveBeneficiary(final Long accountId, final SavingsBeneficiaryRequest request) {
        SavingsBeneficiary beneficiary = null;
        if (request.getId() != null) {
            beneficiary = beneficiaryRepository.findById(request.getId()).orElseThrow(() -> notFound("beneficiary", request.getId()));
        } else if (StringUtils.isNotBlank(request.getExternalId())) {
            beneficiary = beneficiaryRepository.findByExternalId(request.getExternalId().trim()).orElse(null);
        }
        if (beneficiary == null) {
            beneficiary = new SavingsBeneficiary();
        } else {
            assertAccount(accountId, beneficiary.getSavingsAccount().getId());
        }
        return beneficiary;
    }

    private SavingsAccount loadAccount(final Long accountId) {
        return savingsAccountRepository.findOneWithNotFoundDetection(accountId);
    }

    private Client loadOptionalClient(final Long clientId) {
        return clientId == null ? null : clientRepository.findById(clientId).orElseThrow(() -> new ClientNotFoundException(clientId));
    }

    private void assertAccount(final Long requestedAccountId, final Long actualAccountId) {
        if (!requestedAccountId.equals(actualAccountId)) {
            throw invalid("error.msg.savings.account.party.account.mismatch", "The related person does not belong to this deposit account");
        }
    }

    private String requiredName(final String value) {
        final String result = trim(value);
        if (result == null) {
            throw invalid("error.msg.savings.account.party.name.required", "A name is required");
        }
        return result;
    }

    private String trim(final String value) {
        return StringUtils.trimToNull(value);
    }

    private void touch(final SavingsBeneficiary beneficiary) {
        final LocalDateTime now = DateUtils.getLocalDateTimeOfTenant();
        if (beneficiary.getCreatedAt() == null) {
            beneficiary.setCreatedAt(now);
        }
        beneficiary.setUpdatedAt(now);
    }

    private void touch(final SavingsAuthorizedPerson person) {
        final LocalDateTime now = DateUtils.getLocalDateTimeOfTenant();
        if (person.getCreatedAt() == null) {
            person.setCreatedAt(now);
        }
        person.setUpdatedAt(now);
    }

    private GeneralPlatformDomainRuleException invalid(final String code, final String message) {
        return new GeneralPlatformDomainRuleException(code, message);
    }

    private GeneralPlatformDomainRuleException notFound(final String type, final Long id) {
        return invalid("error.msg.savings.account.party.not.found", "Savings account " + type + " " + id + " was not found");
    }
}
