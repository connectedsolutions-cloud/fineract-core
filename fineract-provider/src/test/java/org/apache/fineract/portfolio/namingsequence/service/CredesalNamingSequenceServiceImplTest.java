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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Optional;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingReservation;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingReservationRepository;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingSequence;
import org.apache.fineract.portfolio.namingsequence.domain.CredesalNamingSequenceRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

class CredesalNamingSequenceServiceImplTest {

    private CredesalNamingSequenceRepository sequenceRepository;
    private CredesalNamingReservationRepository reservationRepository;
    private JdbcTemplate jdbcTemplate;
    private CredesalNamingSequenceServiceImpl service;
    private CredesalNamingSequence heldSequence;

    @BeforeEach
    void setUp() {
        sequenceRepository = mock(CredesalNamingSequenceRepository.class);
        reservationRepository = mock(CredesalNamingReservationRepository.class);
        jdbcTemplate = mock(JdbcTemplate.class);
        service = new CredesalNamingSequenceServiceImpl(sequenceRepository, reservationRepository, jdbcTemplate);
        heldSequence = null;

        when(sequenceRepository.findByNamespaceAndPrefixForUpdate(anyString(), anyString()))
                .thenAnswer(invocation -> Optional.ofNullable(heldSequence));
        when(sequenceRepository.saveAndFlush(any(CredesalNamingSequence.class))).thenAnswer(invocation -> {
            heldSequence = invocation.getArgument(0);
            return heldSequence;
        });
        when(sequenceRepository.save(any(CredesalNamingSequence.class))).thenAnswer(invocation -> {
            heldSequence = invocation.getArgument(0);
            return heldSequence;
        });
        when(reservationRepository.findByNamespaceAndReservationKey(anyString(), anyString())).thenReturn(Optional.empty());
        when(reservationRepository.save(any(CredesalNamingReservation.class))).thenAnswer(invocation -> invocation.getArgument(0));
        when(jdbcTemplate.queryForList(anyString(), eq(String.class), any(), anyInt())).thenReturn(List.of());
        when(jdbcTemplate.queryForObject(contains("m_client"), eq(Integer.class), anyString())).thenReturn(1);
        when(jdbcTemplate.queryForObject(contains("account_no ="), eq(Integer.class), anyString())).thenReturn(0);
        when(jdbcTemplate.queryForObject(contains("certificate_number ="), eq(Integer.class), anyString())).thenReturn(0);
    }

    @Test
    void allocatesSpecExamplesThenNextOrdinal() {
        final Client client = affiliatedClient();

        assertEquals("006583M101", service.allocateLoanAccountNo(client, "3M1", null).orElseThrow());
        assertEquals("006583M102", service.allocateLoanAccountNo(client, "3M1", null).orElseThrow());

        heldSequence = null;
        assertEquals("006584V101", service.allocateSavingsAccountNo(client, "4V1", null).orElseThrow());
        heldSequence = null;
        assertEquals("006585D301", service.allocateSavingsAccountNo(client, "5D3", null).orElseThrow());
        heldSequence = null;
        assertEquals("006581AC01", service.allocateShareCertificateNumber(client, "1AC", null));
        heldSequence = null;
        assertEquals("006581AP01", service.allocateShareCertificateNumber(client, "1AP", null));
    }

    @Test
    void missingAffiliationFallsBackInsteadOfInventingAPrefix() {
        final Client client = mock(Client.class);
        when(client.getExternalId()).thenReturn(new ExternalId("not-numeric"));

        assertTrue(service.allocateLoanAccountNo(client, "3M1", null).isEmpty());
        assertTrue(service.allocateSavingsAccountNo(client, "4V1", null).isEmpty());
    }

    @Test
    void collidingPartyPrefixFallsBack() {
        when(jdbcTemplate.queryForObject(contains("m_client"), eq(Integer.class), eq("00658"))).thenReturn(2);

        assertTrue(service.allocateLoanAccountNo(affiliatedClient(), "3M1", null).isEmpty());
    }

    @Test
    void missingNumberingCodeFallsBackToFineractGenerator() {
        assertTrue(service.allocateLoanAccountNo(affiliatedClient(), null, null).isEmpty());
        assertTrue(service.allocateSavingsAccountNo(affiliatedClient(), "5D4", null).isEmpty());
    }

    @Test
    void skipsImportedSuffixAndLeavesSourceGapsClosed() {
        when(jdbcTemplate.queryForList(anyString(), eq(String.class), any(), anyInt())).thenReturn(List.of("006583M105"));

        assertEquals("006583M106", service.allocateLoanAccountNo(affiliatedClient(), "3M1", null).orElseThrow());
    }

    @Test
    void skipsAlreadyUsedCandidate() {
        when(jdbcTemplate.queryForObject(contains("account_no ="), eq(Integer.class), eq("006583M101"))).thenReturn(1);
        when(jdbcTemplate.queryForObject(contains("account_no ="), eq(Integer.class), eq("006583M102"))).thenReturn(0);

        assertEquals("006583M102", service.allocateLoanAccountNo(affiliatedClient(), "3M1", null).orElseThrow());
    }

    @Test
    void exhaustsAtNinetyNineWithoutWrapping() {
        heldSequence = CredesalNamingSequence.create("LOAN", "006583M1", 99);
        when(jdbcTemplate.queryForObject(contains("account_no ="), eq(Integer.class), anyString())).thenReturn(1);

        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.allocateLoanAccountNo(affiliatedClient(), "3M1", null));
    }

    @Test
    void reservationRetryReturnsTheSameValue() {
        final CredesalNamingReservation reservation = CredesalNamingReservation.create("LOAN", "loan-create-1", "006583M101");
        when(reservationRepository.findByNamespaceAndReservationKey("LOAN", "loan-create-1")).thenReturn(Optional.empty())
                .thenReturn(Optional.of(reservation));

        assertEquals("006583M101", service.allocateLoanAccountNo(affiliatedClient(), "3M1", "loan-create-1").orElseThrow());
        assertEquals("006583M101", service.allocateLoanAccountNo(affiliatedClient(), "3M1", "loan-create-1").orElseThrow());
        assertEquals(1, heldSequence.getLastOrdinal());
    }

    @Test
    void allocatesGlobalPassbookNumbersThenExhaustsAt999() {
        assertEquals("001", service.allocateVistaPassbookNumber(null));
        assertEquals("002", service.allocateVistaPassbookNumber(null));

        heldSequence = CredesalNamingSequence.create("VISTA_PASSBOOK", "", 999);
        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.allocateVistaPassbookNumber(null));
    }

    @Test
    void certificateThrowsWhenIneligible() {
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.allocateShareCertificateNumber(mock(Client.class), "1AC", null));
    }

    private static Client affiliatedClient() {
        final Client client = mock(Client.class);
        when(client.getExternalId()).thenReturn(new ExternalId("0000000658"));
        return client;
    }
}
