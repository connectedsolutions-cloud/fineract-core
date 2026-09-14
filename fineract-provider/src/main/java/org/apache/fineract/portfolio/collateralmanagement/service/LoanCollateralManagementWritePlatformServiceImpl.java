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
package org.apache.fineract.portfolio.collateralmanagement.service;

import java.math.BigDecimal;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagement;
import org.apache.fineract.portfolio.collateralmanagement.domain.ClientCollateralManagementRepositoryWrapper;
import org.apache.fineract.portfolio.collateralmanagement.domain.CollateralValuation;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagement;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCollateralManagementRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.springframework.transaction.annotation.Transactional;

@RequiredArgsConstructor
public class LoanCollateralManagementWritePlatformServiceImpl implements LoanCollateralManagementWritePlatformService {

    private final LoanCollateralManagementRepository loanCollateralManagementRepository;
    private final ClientCollateralManagementRepositoryWrapper clientCollateralManagementRepositoryWrapper;
    private final LoanRepositoryWrapper loanRepositoryWrapper;
    private final CollateralDetailService collateralDetailService;

    @Transactional
    @Override
    public CommandProcessingResult deleteLoanCollateral(JsonCommand command) {
        final Long id = command.entityId();
        final LoanCollateralManagement loanCollateralManagement = this.loanCollateralManagementRepository.findById(id).orElseThrow();
        ClientCollateralManagement clientCollateralManagement = loanCollateralManagement.getClientCollateralManagement();
        BigDecimal loanQuantity = loanCollateralManagement.getQuantity();
        BigDecimal clientQuantity = clientCollateralManagement.getQuantity();
        clientCollateralManagement.updateQuantity(clientQuantity.add(loanQuantity));
        this.clientCollateralManagementRepositoryWrapper.saveAndFlush(clientCollateralManagement);
        this.loanCollateralManagementRepository.deleteById(id);
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(id).withLoanId(command.getLoanId())
                .build();
    }

    @Transactional
    @Override
    public CommandProcessingResult sourceExactAttachLoanCollateral(JsonCommand command) {
        final Long loanId = command.getLoanId();
        final Long clientCollateralId = command.longValueOfParameterNamed("clientCollateralId");
        final BigDecimal quantity = command.bigDecimalValueOfParameterNamed("quantity");
        final Long valuationId = command.longValueOfParameterNamed("valuationId");
        if (clientCollateralId == null || quantity == null || quantity.signum() <= 0 || valuationId == null) {
            throw rule("invalid", "clientCollateralId, a positive quantity, and valuationId are required");
        }

        final Loan loan = this.loanRepositoryWrapper.findOneWithNotFoundDetection(loanId, true);
        final ClientCollateralManagement clientCollateral = this.clientCollateralManagementRepositoryWrapper
                .getCollateral(clientCollateralId);
        if (!clientCollateral.getClient().getId().equals(loan.getClientId())) {
            throw rule("client.mismatch", "The collateral and loan must belong to the same client");
        }

        final boolean released = loan.isClosed();
        final List<LoanCollateralManagement> existingCollaterals = this.loanCollateralManagementRepository.findByLoan(loan);
        for (LoanCollateralManagement existing : existingCollaterals) {
            if (existing.getClientCollateralManagement().getId().equals(clientCollateralId)) {
                if (existing.getQuantity().compareTo(quantity) == 0 && valuationId.equals(existing.getValuationId())
                        && existing.isReleased() == released) {
                    return result(command, loan, existing.getId());
                }
                throw rule("conflict", "The loan already has a different attachment for this collateral");
            }
        }

        final CollateralValuation valuation = this.collateralDetailService.requireFinalValuation(clientCollateralId, valuationId);
        if (!released) {
            if (clientCollateral.getQuantity().compareTo(quantity) < 0) {
                throw rule("quantity.unavailable", "The collateral quantity available to the client is insufficient");
            }
            clientCollateral.updateQuantity(clientCollateral.getQuantity().subtract(quantity));
            this.clientCollateralManagementRepositoryWrapper.saveAndFlush(clientCollateral);
        }

        final BigDecimal pledgedValue = valuation.getTotalValue().multiply(quantity);
        final BigDecimal eligibleValue = pledgedValue.multiply(clientCollateral.getCollaterals().getPctToBase())
                .divide(BigDecimal.valueOf(100));
        final LoanCollateralManagement loanCollateral = LoanCollateralManagement.from(clientCollateral, quantity);
        loanCollateral.setLoan(loan);
        loanCollateral.setIsReleased(released);
        loanCollateral.applyValuationSnapshot(valuationId, pledgedValue, eligibleValue, valuation.getValuationDate());
        final LoanCollateralManagement saved = this.loanCollateralManagementRepository.saveAndFlush(loanCollateral);
        return result(command, loan, saved.getId());
    }

    private CommandProcessingResult result(JsonCommand command, Loan loan, Long entityId) {
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(entityId).withLoanId(loan.getId())
                .withClientId(loan.getClientId()).build();
    }

    private GeneralPlatformDomainRuleException rule(String suffix, String message) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.collateral.source.exact." + suffix, message);
    }
}
