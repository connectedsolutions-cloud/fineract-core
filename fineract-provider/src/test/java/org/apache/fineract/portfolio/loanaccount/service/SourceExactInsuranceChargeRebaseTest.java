/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software distributed under the License is
 * distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.portfolio.charge.domain.ChargeCalculationType;
import org.apache.fineract.portfolio.charge.domain.ChargeTimeType;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargeRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class SourceExactInsuranceChargeRebaseTest {

    @Mock
    private LoanAssembler loanAssembler;
    @Mock
    private LoanChargeRepository loanChargeRepository;
    @Mock
    private LoanRepositoryWrapper loanRepositoryWrapper;
    @Mock
    private ReprocessLoanTransactionsService reprocessLoanTransactionsService;
    @Mock
    private BusinessEventNotifierService businessEventNotifierService;
    @Mock
    private JsonCommand command;
    @Mock
    private Loan loan;
    @InjectMocks
    private LoanChargeWritePlatformServiceImpl service;

    private LoanCharge charge;

    @BeforeEach
    void setUp() {
        charge = new LoanCharge();
        charge.setLoan(loan);
        charge.setExternalId(new ExternalId("ARISSTO:CRD-INS-CUTOVER:2100"));
        charge.setChargeTime(ChargeTimeType.SPECIFIED_DUE_DATE.getValue());
        charge.setChargeCalculation(ChargeCalculationType.FLAT.getValue());
        charge.setAmount(new BigDecimal("1.26"));
        charge.setAmountPaid(new BigDecimal("0.72"));
        charge.setAmountOutstanding(new BigDecimal("0.54"));
        when(command.stringValueOfParameterNamed("sourceSystem")).thenReturn("ARISSTO");
        when(command.bigDecimalValueOfParameterNamed("sourceOutstanding")).thenReturn(new BigDecimal("1.53"));
        when(loanAssembler.assembleFrom(55L)).thenReturn(loan);
        when(loanChargeRepository.findById(99L)).thenReturn(Optional.of(charge));
        when(loan.hasIdentifyOf(55L)).thenReturn(true);
        when(loan.getStatus()).thenReturn(LoanStatus.ACTIVE);
    }

    @Test
    void rebaseUpdatesNativeChargeAndReprocessesLoan() {
        service.rebaseSourceExactInsuranceCharge(55L, 99L, command);

        assertEquals(0, charge.amountOutstanding().compareTo(new BigDecimal("1.53")));
        assertEquals(0, charge.getAmountPaid().compareTo(new BigDecimal("0.72")));
        verify(reprocessLoanTransactionsService).reprocessTransactions(loan);
        verify(loanRepositoryWrapper).save(loan);
    }

    @Test
    void exactReplayMakesNoWrite() {
        charge.setAmountOutstanding(new BigDecimal("1.53"));

        service.rebaseSourceExactInsuranceCharge(55L, 99L, command);

        verify(reprocessLoanTransactionsService, never()).reprocessTransactions(loan);
        verify(loanRepositoryWrapper, never()).save(loan);
    }

    @Test
    void rebaseConvergesAfterReprocessingChangesThePaidAmount() {
        AtomicInteger calls = new AtomicInteger();
        doAnswer(invocation -> {
            if (calls.getAndIncrement() == 0) {
                charge.setAmountPaid(new BigDecimal("0.80"));
                charge.setAmountOutstanding(new BigDecimal("0.40"));
            }
            return null;
        }).when(reprocessLoanTransactionsService).reprocessTransactions(loan);

        service.rebaseSourceExactInsuranceCharge(55L, 99L, command);

        assertEquals(0, charge.amountOutstanding().compareTo(new BigDecimal("1.53")));
        assertEquals(0, charge.getAmount().compareTo(new BigDecimal("2.33")));
        verify(reprocessLoanTransactionsService, times(2)).reprocessTransactions(loan);
    }

    @Test
    void otherChargeIdentityCannotUseMigrationCommand() {
        charge.setExternalId(new ExternalId("OTHER:CHARGE:2100"));

        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.rebaseSourceExactInsuranceCharge(55L, 99L, command));
        verify(loanRepositoryWrapper, never()).save(loan);
    }
}
