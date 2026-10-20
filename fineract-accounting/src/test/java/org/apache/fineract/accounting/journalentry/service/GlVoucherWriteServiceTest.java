/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor
 * license agreements. See the NOTICE file distributed with this work for
 * additional information regarding copyright ownership. The ASF licenses this
 * file to you under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain a
 * copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.accounting.journalentry.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;
import java.util.Optional;
import org.apache.fineract.accounting.journalentry.domain.GlAuxiliar;
import org.apache.fineract.accounting.journalentry.domain.GlAuxiliarRepository;
import org.apache.fineract.accounting.journalentry.domain.GlVoucher;
import org.apache.fineract.accounting.journalentry.domain.GlVoucherRepository;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class GlVoucherWriteServiceTest {

    private final GlVoucherRepository voucherRepository = mock(GlVoucherRepository.class);
    private final GlAuxiliarRepository auxiliarRepository = mock(GlAuxiliarRepository.class);
    private final GlVoucherWriteService service = new GlVoucherWriteService(voucherRepository, auxiliarRepository);

    @BeforeEach
    void saveReturnsVoucher() {
        when(voucherRepository.saveAndFlush(any(GlVoucher.class))).thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void historicalImportPreservesKnownAuxiliarAndHeaderConcept() {
        when(auxiliarRepository.existsById("4")).thenReturn(true);

        GlVoucher voucher = service.createHistorical(" 4 ", " Source concept ", "Fallback description", "317", "001");

        assertThat(voucher.getAuxiliarCode()).isEqualTo("4");
        assertThat(voucher.getHeaderConcept()).isEqualTo("Source concept");
        assertThat(voucher.getOrigin()).isEqualTo("ARISSTO_HISTORICAL_GL_IMPORT");
        assertThat(voucher.getSourceEntityType()).isEqualTo("ARISSTO_JOURNAL");
        assertThat(voucher.getSourceEntityId()).isEqualTo("317");
        assertThat(voucher.getPostingCategory()).isEqualTo("REGULAR");
    }

    @Test
    void unknownHistoricalCodeDoesNotBlockImport() {
        GlVoucher voucher = service.createHistorical("999", " ", "Fallback description", "318", "001");

        assertThat(voucher.getAuxiliarCode()).isNull();
        assertThat(voucher.getHeaderConcept()).isEqualTo("Fallback description");
        verify(voucherRepository).saveAndFlush(any(GlVoucher.class));
    }

    @Test
    void annualLiquidationUsesNativeClosingCategory() {
        GlVoucher voucher = service.createHistorical("999", "Annual liquidation", null, "319", "003");

        assertThat(voucher.getPostingCategory()).isEqualTo("CLOSING");
    }

    @Test
    void manualJournalRequiresApprovedCode() {
        GlAuxiliar auxiliar = mock(GlAuxiliar.class);
        when(auxiliar.isActive()).thenReturn(true);
        when(auxiliarRepository.findById("1")).thenReturn(Optional.of(auxiliar));

        assertThatThrownBy(() -> service.createManual("1", "Adjustment")).isInstanceOf(GeneralPlatformDomainRuleException.class)
                .hasMessageContaining("not approved");
        verify(voucherRepository, never()).saveAndFlush(any(GlVoucher.class));
    }

    @Test
    void manualJournalStoresSelectedApprovedCode() {
        GlAuxiliar auxiliar = mock(GlAuxiliar.class);
        when(auxiliar.isActive()).thenReturn(true);
        when(auxiliar.isManualAllowed()).thenReturn(true);
        when(auxiliar.getCode()).thenReturn("25");
        when(auxiliarRepository.findById("25")).thenReturn(Optional.of(auxiliar));

        GlVoucher voucher = service.createManual("25", "Adjustment");

        assertThat(voucher.getAuxiliarCode()).isEqualTo("25");
        assertThat(voucher.getHeaderConcept()).isEqualTo("Adjustment");
        assertThat(voucher.getOperationType()).isEqualTo("MANUAL_JOURNAL");
    }

    @Test
    void nativeRoutesUseTheApprovedAuxiliarMapAndKeepTheirSource() {
        when(auxiliarRepository.findById(anyString())).thenAnswer(invocation -> {
            String code = invocation.getArgument(0);
            GlAuxiliar auxiliar = mock(GlAuxiliar.class);
            when(auxiliar.isActive()).thenReturn(true);
            when(auxiliar.getCode()).thenReturn(code);
            return Optional.of(auxiliar);
        });

        for (Map.Entry<String, String> rule : Map.of("TELLER_ALLOCATE", "3:CASHIER_TRANSACTION", "TELLER_SETTLE",
                "3:CASHIER_TRANSACTION", "TELLER_TO_VAULT", "20:TELLER_VAULT_TRANSFER", "VAULT_TO_TELLER",
                "20:TELLER_VAULT_TRANSFER", "COMITE_VAULT_RECEPTION", "20:COMITE_SESSION", "COMITE_CASHIER_RECEPTION",
                "3:COMITE_SESSION", "COMITE_DISBURSEMENT_CLEARING", "4:COMITE_SESSION").entrySet()) {
            String[] expected = rule.getValue().split(":");
            GlVoucher voucher = service.createNative(rule.getKey(), "Approved route concept", expected[1], "41");

            assertThat(voucher.getAuxiliarCode()).isEqualTo(expected[0]);
            assertThat(voucher.getAuxiliarRuleVersion()).isEqualTo("2026-10-12-v1");
            assertThat(voucher.getOrigin()).isEqualTo("NATIVE_OPERATION");
            assertThat(voucher.getOperationType()).isEqualTo(rule.getKey());
            assertThat(voucher.getSourceEntityType()).isEqualTo(expected[1]);
            assertThat(voucher.getSourceEntityId()).isEqualTo("41");
        }
    }

    @Test
    void nativeRouteWithoutAnApprovedRuleDoesNotPost() {
        assertThatThrownBy(() -> service.createNative("OTHER_ROUTE", "Concept", "SOURCE_RECORD", "41"))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("No approved Auxiliar rule");
        verify(voucherRepository, never()).saveAndFlush(any(GlVoucher.class));
    }

    @Test
    void nativeRouteRejectsAnInactiveApprovedAuxiliar() {
        GlAuxiliar auxiliar = mock(GlAuxiliar.class);
        when(auxiliarRepository.findById("20")).thenReturn(Optional.of(auxiliar));

        assertThatThrownBy(() -> service.createNative("VAULT_TO_TELLER", "Concept", "TELLER_VAULT_TRANSFER", "41"))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("inactive");
        verify(voucherRepository, never()).saveAndFlush(any(GlVoucher.class));
    }

    @Test
    void nativeRouteRejectsTheWrongSourcePointerType() {
        assertThatThrownBy(() -> service.createNative("TELLER_ALLOCATE", "Concept", "COMITE_SESSION", "41"))
                .isInstanceOf(GeneralPlatformDomainRuleException.class).hasMessageContaining("source type");
        verify(voucherRepository, never()).saveAndFlush(any(GlVoucher.class));
    }

    @Test
    void reversalCanUseItsRouteCodeAndKeepsOriginalLink() {
        GlVoucher original = GlVoucher.create("4", "Original", "MANUAL", "MANUAL_JOURNAL", null, null, null);
        GlAuxiliar auxiliar = mock(GlAuxiliar.class);
        when(auxiliar.isActive()).thenReturn(true);
        when(auxiliar.getCode()).thenReturn("12");
        when(auxiliarRepository.findById("12")).thenReturn(Optional.of(auxiliar));

        GlVoucher reversal = service.createReversal(original, "12", "Reversal", "LOAN_REVERSAL");

        assertThat(reversal.getAuxiliarCode()).isEqualTo("12");
        assertThat(reversal.getReversesVoucher()).isSameAs(original);
        assertThat(reversal.getOperationType()).isEqualTo("LOAN_REVERSAL");
    }
}
