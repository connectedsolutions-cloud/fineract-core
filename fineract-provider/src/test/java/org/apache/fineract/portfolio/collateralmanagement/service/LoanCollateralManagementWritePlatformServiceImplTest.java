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
 */
package org.apache.fineract.portfolio.collateralmanagement.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagement;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagementRepositoryWrapper;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralManagementDomain;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuation;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagement;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagementRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class LoanCollateralManagementWritePlatformServiceImplTest {

    private LoanCollateralManagementRepository loanCollateralRepository;
    private ClientCollateralManagementRepositoryWrapper clientCollateralRepository;
    private LoanRepositoryWrapper loanRepository;
    private CollateralDetailService collateralDetailService;
    private LoanCollateralManagementWritePlatformServiceImpl service;
    private JsonCommand command;
    private Loan loan;
    private ClientCollateralManagement clientCollateral;
    private CollateralValuation valuation;

    @BeforeEach
    void setUp() {
        loanCollateralRepository = mock(LoanCollateralManagementRepository.class);
        clientCollateralRepository = mock(ClientCollateralManagementRepositoryWrapper.class);
        loanRepository = mock(LoanRepositoryWrapper.class);
        collateralDetailService = mock(CollateralDetailService.class);
        service = new LoanCollateralManagementWritePlatformServiceImpl(loanCollateralRepository, clientCollateralRepository,
                loanRepository, collateralDetailService);

        command = mock(JsonCommand.class);
        when(command.getLoanId()).thenReturn(20L);
        when(command.longValueOfParameterNamed("clientCollateralId")).thenReturn(10L);
        when(command.bigDecimalValueOfParameterNamed("quantity")).thenReturn(BigDecimal.ONE);
        when(command.longValueOfParameterNamed("valuationId")).thenReturn(30L);

        loan = mock(Loan.class);
        when(loan.getId()).thenReturn(20L);
        when(loan.getClientId()).thenReturn(3L);
        when(loanRepository.findOneWithNotFoundDetection(20L, true)).thenReturn(loan);

        Client client = mock(Client.class);
        when(client.getId()).thenReturn(3L);
        CollateralManagementDomain product = mock(CollateralManagementDomain.class);
        when(product.getPctToBase()).thenReturn(new BigDecimal("80"));
        clientCollateral = mock(ClientCollateralManagement.class);
        when(clientCollateral.getId()).thenReturn(10L);
        when(clientCollateral.getClient()).thenReturn(client);
        when(clientCollateral.getCollaterals()).thenReturn(product);
        when(clientCollateral.getQuantity()).thenReturn(BigDecimal.ONE);
        when(clientCollateralRepository.getCollateral(10L)).thenReturn(clientCollateral);

        valuation = mock(CollateralValuation.class);
        when(valuation.getTotalValue()).thenReturn(new BigDecimal("5000"));
        when(valuation.getValuationDate()).thenReturn(LocalDate.of(2026, 8, 31));
        when(collateralDetailService.requireFinalValuation(10L, 30L)).thenReturn(valuation);
        when(loanCollateralRepository.findByLoan(loan)).thenReturn(List.of());
        when(loanCollateralRepository.saveAndFlush(any())).thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void activeLoanReservesQuantityAndStoresValuationSnapshot() {
        when(loan.isClosed()).thenReturn(false);

        service.sourceExactAttachLoanCollateral(command);

        verify(clientCollateral).updateQuantity(BigDecimal.ZERO);
        verify(clientCollateralRepository).saveAndFlush(clientCollateral);
        ArgumentCaptor<LoanCollateralManagement> saved = ArgumentCaptor.forClass(LoanCollateralManagement.class);
        verify(loanCollateralRepository).saveAndFlush(saved.capture());
        assertFalse(saved.getValue().isReleased());
        assertEquals(new BigDecimal("5000"), saved.getValue().getPledgedValue());
        assertEquals(new BigDecimal("4000"), saved.getValue().getEligibleValue());
        assertEquals(30L, saved.getValue().getValuationId());
    }

    @Test
    void closedLoanStoresReleasedAttachmentWithoutReservingQuantity() {
        when(loan.isClosed()).thenReturn(true);

        service.sourceExactAttachLoanCollateral(command);

        verify(clientCollateral, never()).updateQuantity(any());
        verify(clientCollateralRepository, never()).saveAndFlush(any());
        ArgumentCaptor<LoanCollateralManagement> saved = ArgumentCaptor.forClass(LoanCollateralManagement.class);
        verify(loanCollateralRepository).saveAndFlush(saved.capture());
        assertTrue(saved.getValue().isReleased());
    }

    @Test
    void exactExistingAttachmentIsIdempotent() {
        when(loan.isClosed()).thenReturn(false);
        LoanCollateralManagement existing = mock(LoanCollateralManagement.class);
        when(existing.getId()).thenReturn(40L);
        when(existing.getClientCollateralManagement()).thenReturn(clientCollateral);
        when(existing.getQuantity()).thenReturn(BigDecimal.ONE);
        when(existing.getValuationId()).thenReturn(30L);
        when(existing.isReleased()).thenReturn(false);
        when(loanCollateralRepository.findByLoan(loan)).thenReturn(List.of(existing));

        service.sourceExactAttachLoanCollateral(command);

        verify(collateralDetailService, never()).requireFinalValuation(any(), any());
        verify(loanCollateralRepository, never()).saveAndFlush(any());
    }
}
