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
package org.apache.fineract.portfolio.namingsequence.service;

import java.util.List;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.namingsequence.CredesalNamingCodes;
import org.apache.fineract.portfolio.namingsequence.CredesalNamingNamespace;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingReservation;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingReservationRepository;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingSequence;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingSequenceRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class CredesalNamingSequenceServiceImpl implements CredesalNamingSequenceService {

    private static final String PARTY_COLLISION_SQL = """
            select count(1) from m_client
             where external_id ~ '^[0-9]{10}$'
               and right(external_id, 5) = ?
            """;

    private final CredesalNamingSequenceRepository sequenceRepository;
    private final CredesalNamingReservationRepository reservationRepository;
    private final JdbcTemplate jdbcTemplate;

    @Override
    @Transactional
    public Optional<String> allocateLoanAccountNo(final Client client, final String numberingCode, final String reservationKey) {
        return allocateIfEligible(CredesalNamingNamespace.LOAN, client, numberingCode, reservationKey);
    }

    @Override
    @Transactional
    public Optional<String> allocateSavingsAccountNo(final Client client, final String numberingCode, final String reservationKey) {
        return allocateIfEligible(CredesalNamingNamespace.SAVINGS, client, numberingCode, reservationKey);
    }

    @Override
    @Transactional
    public String allocateShareCertificateNumber(final Client client, final String numberingCode, final String reservationKey) {
        return allocateIfEligible(CredesalNamingNamespace.SHARE_CERTIFICATE, client, numberingCode, reservationKey)
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.credesal.naming.certificate.ineligible",
                        "Cannot allocate a share certificate number without a valid affiliation prefix and numbering code."));
    }

    @Override
    @Transactional
    public String allocateVistaPassbookNumber(final String reservationKey) {
        return allocate(CredesalNamingNamespace.VISTA_PASSBOOK, "", reservationKey);
    }

    private Optional<String> allocateIfEligible(final CredesalNamingNamespace namespace, final Client client, final String numberingCode,
            final String reservationKey) {
        final String normalized = CredesalNamingCodes.normalize(numberingCode);
        if (normalized == null || !CredesalNamingCodes.isValid(namespace, normalized)) {
            return Optional.empty();
        }
        final Optional<String> partyPrefix = resolvePartyPrefix(client);
        if (partyPrefix.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(allocate(namespace, CredesalNamingCodes.composePrefix(partyPrefix.get(), normalized), reservationKey));
    }

    private Optional<String> resolvePartyPrefix(final Client client) {
        if (client == null) {
            return Optional.empty();
        }
        final ExternalId externalId = client.getExternalId();
        if (externalId == null || externalId.isEmpty()) {
            return Optional.empty();
        }
        final Optional<String> partyPrefix = CredesalNamingCodes.extractPartyPrefix(externalId.getValue());
        if (partyPrefix.isEmpty()) {
            return Optional.empty();
        }
        final Integer matchingClients = jdbcTemplate.queryForObject(PARTY_COLLISION_SQL, Integer.class, partyPrefix.get());
        if (matchingClients != null && matchingClients > 1) {
            return Optional.empty();
        }
        return partyPrefix;
    }

    private String allocate(final CredesalNamingNamespace namespace, final String prefix, final String reservationKey) {
        if (StringUtils.isNotBlank(reservationKey)) {
            final Optional<CredesalNamingReservation> existing = reservationRepository
                    .findByNamespaceAndReservationKey(namespace.name(), reservationKey);
            if (existing.isPresent()) {
                return existing.get().getAllocatedValue();
            }
        }

        final CredesalNamingSequence sequence = lockOrCreate(namespace, prefix);
        int next = sequence.getLastOrdinal() + 1;
        while (next <= namespace.getMaxOrdinal()) {
            final String candidate = CredesalNamingCodes.formatValue(prefix, next, namespace.getOrdinalWidth());
            if (!valueExists(namespace, candidate)) {
                sequence.setLastOrdinal(next);
                sequenceRepository.save(sequence);
                if (StringUtils.isNotBlank(reservationKey)) {
                    reservationRepository.save(CredesalNamingReservation.create(namespace.name(), reservationKey, candidate));
                }
                return candidate;
            }
            next++;
        }
        throw new GeneralPlatformDomainRuleException("error.msg.credesal.naming.exhausted",
                "Naming sequence exhausted for " + namespace + " prefix " + prefix + ".");
    }

    private CredesalNamingSequence lockOrCreate(final CredesalNamingNamespace namespace, final String prefix) {
        final Optional<CredesalNamingSequence> existing = sequenceRepository.findByNamespaceAndPrefixForUpdate(namespace.name(), prefix);
        if (existing.isPresent()) {
            return existing.get();
        }
        try {
            return sequenceRepository.saveAndFlush(CredesalNamingSequence.create(namespace.name(), prefix, seedOrdinal(namespace, prefix)));
        } catch (final DataIntegrityViolationException ex) {
            return sequenceRepository.findByNamespaceAndPrefixForUpdate(namespace.name(), prefix)
                    .orElseThrow(() -> ex);
        }
    }

    private int seedOrdinal(final CredesalNamingNamespace namespace, final String prefix) {
        final String sql = existingValuesSql(namespace);
        if (sql == null) {
            return 0;
        }
        final int expectedLength = prefix.length() + namespace.getOrdinalWidth();
        final List<String> values = jdbcTemplate.queryForList(sql, String.class, prefix + "%", expectedLength);
        int max = 0;
        for (final String value : values) {
            final Optional<Integer> ordinal = CredesalNamingCodes.parseOrdinal(value, prefix, namespace.getOrdinalWidth());
            if (ordinal.isPresent() && ordinal.get() > max) {
                max = ordinal.get();
            }
        }
        return max;
    }

    private boolean valueExists(final CredesalNamingNamespace namespace, final String value) {
        final String sql = uniquenessSql(namespace);
        if (sql == null) {
            return false;
        }
        final Integer count = jdbcTemplate.queryForObject(sql, Integer.class, value);
        return count != null && count > 0;
    }

    private static String existingValuesSql(final CredesalNamingNamespace namespace) {
        return switch (namespace) {
            case LOAN -> "select account_no from m_loan where account_no like ? and length(account_no) = ?";
            case SAVINGS -> "select account_no from m_savings_account where account_no like ? and length(account_no) = ?";
            case SHARE_CERTIFICATE ->
                "select certificate_number from credesal_share_certificate where certificate_number like ? and length(certificate_number) = ?";
            case VISTA_PASSBOOK -> null;
        };
    }

    private static String uniquenessSql(final CredesalNamingNamespace namespace) {
        return switch (namespace) {
            case LOAN -> "select count(1) from m_loan where account_no = ?";
            case SAVINGS -> "select count(1) from m_savings_account where account_no = ?";
            case SHARE_CERTIFICATE -> "select count(1) from credesal_share_certificate where certificate_number = ?";
            case VISTA_PASSBOOK -> null;
        };
    }
}
