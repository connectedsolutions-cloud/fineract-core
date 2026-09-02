/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information regarding copyright ownership. The ASF licenses this file to
 * you under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the
 * License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
 * an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Locale;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.portfolio.charge.domain.Charge;
import org.apache.fineract.portfolio.charge.domain.ChargeCalculationType;
import org.apache.fineract.portfolio.charge.domain.ChargeRepositoryWrapper;
import org.apache.fineract.portfolio.charge.domain.ChargeTimeType;
import org.apache.fineract.portfolio.loanaccount.api.LoanApiConstants;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargeRepository;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class LoanChargeAssemblerSubmittedOnDateTest {

    private final ChargeRepositoryWrapper chargeRepository = mock(ChargeRepositoryWrapper.class);
    private final LoanChargeRepository loanChargeRepository = mock(LoanChargeRepository.class);
    private final LoanProductRepository loanProductRepository = mock(LoanProductRepository.class);
    private final ExternalIdFactory externalIdFactory = mock(ExternalIdFactory.class);
    private final LoanChargeService loanChargeService = mock(LoanChargeService.class);
    private final org.apache.fineract.infrastructure.core.serialization.FromJsonHelper fromJsonHelper = mock(
            org.apache.fineract.infrastructure.core.serialization.FromJsonHelper.class);
    private final LoanChargeAssembler underTest = new LoanChargeAssembler(fromJsonHelper, chargeRepository, loanChargeRepository,
            loanProductRepository, externalIdFactory, loanChargeService);

    private final JsonCommand command = mock(JsonCommand.class);
    private final Loan loan = mock(Loan.class);
    private final Charge charge = mock(Charge.class);
    private final LoanCharge createdCharge = mock(LoanCharge.class);

    @BeforeEach
    void setUp() {
        when(command.extractLocale()).thenReturn(Locale.ENGLISH);
        when(command.bigDecimalValueOfParameterNamed("amount", Locale.ENGLISH)).thenReturn(new BigDecimal("0.06"));
        when(charge.getChargeCalculation()).thenReturn(ChargeCalculationType.FLAT.getValue());
        when(charge.getChargeTimeType()).thenReturn(ChargeTimeType.SPECIFIED_DUE_DATE.getValue());
        when(externalIdFactory.createFromCommand(command, "externalId")).thenReturn(ExternalId.empty());
        when(loanChargeService.create(any(), any(), any(), any(), isNull(), isNull(), isNull(), isNull(), isNull(), any(), any()))
                .thenReturn(createdCharge);
    }

    @Test
    void copiesOptionalSubmittedOnDateToNewCharge() {
        LocalDate cutoverDate = LocalDate.of(2026, 8, 31);
        when(command.hasParameter(LoanApiConstants.submittedOnDateParameterName)).thenReturn(true);
        when(command.localDateValueOfParameterNamed(LoanApiConstants.submittedOnDateParameterName)).thenReturn(cutoverDate);

        underTest.createNewFromJson(loan, charge, command, null);

        verify(createdCharge).setSubmittedOnDate(cutoverDate);
    }

    @Test
    void leavesNormalChargeUnchangedWhenSubmittedOnDateIsAbsent() {
        when(command.hasParameter(LoanApiConstants.submittedOnDateParameterName)).thenReturn(false);

        underTest.createNewFromJson(loan, charge, command, null);

        verify(createdCharge, never()).setSubmittedOnDate(any());
    }
}
