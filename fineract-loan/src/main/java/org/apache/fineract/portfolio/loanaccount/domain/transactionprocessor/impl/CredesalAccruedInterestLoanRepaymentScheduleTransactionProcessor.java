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
package org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionToRepaymentScheduleMapping;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;

public class CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor
        extends DuePenFeeIntPriInAdvancePriPenFeeIntLoanRepaymentScheduleTransactionProcessor {

    public static final String STRATEGY_CODE = "credesal-accrued-interest-first-strategy";
    public static final String STRATEGY_NAME = "Credesal post-due interest with due-first allocation";

    private final PostDueAccruedInterestCalculator accruedInterestCalculator;

    public CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(final ExternalIdFactory externalIdFactory,
            final LoanChargeValidator loanChargeValidator, final LoanBalanceService loanBalanceService,
            final PostDueAccruedInterestCalculator accruedInterestCalculator) {
        super(externalIdFactory, loanChargeValidator, loanBalanceService);
        this.accruedInterestCalculator = accruedInterestCalculator;
    }

    @Override
    public String getCode() {
        return STRATEGY_CODE;
    }

    @Override
    public String getName() {
        return STRATEGY_NAME;
    }

    @Override
    protected Money processTransaction(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments, final Set<LoanCharge> charges, final Money amountToProcess) {
        accruedInterestCalculator.calculateAndApply(loanTransaction, currency, installments);
        if (loanTransaction.isSourceExactComponentReallocation()) {
            return processSourceExactComponentReallocation(loanTransaction, currency, installments);
        }
        if (loanTransaction.isSourceExactAllocation()) {
            materializeSourceExactPostDueInterest(loanTransaction, currency, installments);
            return processSourceExactRepayment(loanTransaction, currency, installments);
        }
        return super.processTransaction(loanTransaction, currency, installments, charges, amountToProcess);
    }

    private Money processSourceExactComponentReallocation(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments) {
        final Money requestedPrincipal = loanTransaction.getSourceExactPrincipalPortion(currency);
        final Money requestedInterest = loanTransaction.getSourceExactInterestPortion(currency);
        if (!requestedPrincipal.isGreaterThanZero() || !requestedInterest.isLessThanZero()
                || !requestedPrincipal.plus(requestedInterest).isZero()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.component.reallocation.invalid",
                    "The source-exact component reallocation must move an equal amount from interest to principal");
        }
        final LoanRepaymentScheduleInstallment interestInstallment = installments.stream()
                .filter(LoanRepaymentScheduleInstallment::isNotFullyPaidOff).findFirst().orElseThrow(
                        () -> new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.component.reallocation.not.representable",
                                "The source-exact component reallocation requires an open repayment installment"));
        interestInstallment.addPostDueInterest(loanTransaction.getTransactionDate(), requestedInterest.negated());

        Money principalRemaining = requestedPrincipal;
        final List<LoanTransactionToRepaymentScheduleMapping> mappings = new ArrayList<>();
        boolean interestMapped = false;
        for (final LoanRepaymentScheduleInstallment installment : installments) {
            final Money principal = installment.payPrincipalComponent(loanTransaction.getTransactionDate(), principalRemaining);
            principalRemaining = principalRemaining.minus(principal);
            final Money interest = installment == interestInstallment ? requestedInterest : Money.zero(currency);
            loanTransaction.updateComponents(principal, interest, Money.zero(currency), Money.zero(currency));
            if (!principal.isZero() || !interest.isZero()) {
                mappings.add(LoanTransactionToRepaymentScheduleMapping.createFrom(loanTransaction, installment, principal, interest,
                        Money.zero(currency), Money.zero(currency)));
            }
            interestMapped |= !interest.isZero();
        }
        loanTransaction.addLoanTransactionToRepaymentScheduleMappings(mappings);
        if (principalRemaining.isGreaterThanZero() || !interestMapped) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.component.reallocation.not.representable",
                    "The source-exact component reallocation cannot be represented by the loan schedule");
        }
        return Money.zero(currency);
    }

    private void materializeSourceExactPostDueInterest(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments) {
        if (installments.isEmpty() || !loanTransaction.getTransactionDate().isAfter(installments.getFirst().getDueDate())) {
            return;
        }
        final Money requestedInterest = loanTransaction.getSourceExactInterestPortion(currency);
        final Money representableInterest = installments.stream().map(installment -> installment.getInterestOutstanding(currency))
                .reduce(Money.zero(currency), Money::add);
        if (!requestedInterest.isGreaterThan(representableInterest)) {
            return;
        }
        final Money sourcePostDueInterest = requestedInterest.minus(representableInterest);
        installments.stream().filter(LoanRepaymentScheduleInstallment::isNotFullyPaidOff)
                .min((left, right) -> left.getDueDate().compareTo(right.getDueDate())).orElse(installments.getFirst())
                .addPostDueInterest(loanTransaction.getTransactionDate(), sourcePostDueInterest);
    }

    private Money processSourceExactRepayment(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments) {
        final LocalDate transactionDate = loanTransaction.getTransactionDate();
        Money principalRemaining = loanTransaction.getSourceExactPrincipalPortion(currency);
        Money interestRemaining = loanTransaction.getSourceExactInterestPortion(currency);
        Money feeRemaining = loanTransaction.getSourceExactFeeChargesPortion(currency);
        Money penaltyRemaining = loanTransaction.getSourceExactPenaltyChargesPortion(currency);
        final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings = new ArrayList<>();

        for (final LoanRepaymentScheduleInstallment installment : installments) {
            final Money principalPortion = installment.payPrincipalComponent(transactionDate, principalRemaining);
            principalRemaining = principalRemaining.minus(principalPortion);
            final Money interestPortion = installment.payInterestComponent(transactionDate, interestRemaining);
            interestRemaining = interestRemaining.minus(interestPortion);
            final Money feePortion = installment.payFeeChargesComponent(transactionDate, feeRemaining);
            feeRemaining = feeRemaining.minus(feePortion);
            final Money penaltyPortion = installment.payPenaltyChargesComponent(transactionDate, penaltyRemaining);
            penaltyRemaining = penaltyRemaining.minus(penaltyPortion);

            loanTransaction.updateComponents(principalPortion, interestPortion, feePortion, penaltyPortion);
            if (principalPortion.plus(interestPortion).plus(feePortion).plus(penaltyPortion).isGreaterThanZero()) {
                transactionMappings.add(LoanTransactionToRepaymentScheduleMapping.createFrom(loanTransaction, installment, principalPortion,
                        interestPortion, feePortion, penaltyPortion));
            }
        }

        loanTransaction.updateLoanTransactionToRepaymentScheduleMappings(transactionMappings);
        if (principalRemaining.isGreaterThanZero() || interestRemaining.isGreaterThanZero() || feeRemaining.isGreaterThanZero()
                || penaltyRemaining.isGreaterThanZero()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.allocation.not.representable",
                    "The source-exact repayment allocation cannot be represented by the loan schedule. Remaining principal: %s, interest: %s, fees: %s, penalties: %s",
                    principalRemaining.getAmount(), interestRemaining.getAmount(), feeRemaining.getAmount(), penaltyRemaining.getAmount());
        }
        return Money.zero(currency);
    }

    @Override
    protected Money handleTransactionThatIsPaymentInAdvanceOfInstallment(final LoanRepaymentScheduleInstallment currentInstallment,
            final List<LoanRepaymentScheduleInstallment> installments, final LoanTransaction loanTransaction, final Money paymentInAdvance,
            final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings, final Set<LoanCharge> charges) {
        if (loanTransaction.isChargesWaiver() || loanTransaction.isInterestWaiver() || loanTransaction.isChargePayment()) {
            return super.handleTransactionThatIsPaymentInAdvanceOfInstallment(currentInstallment, installments, loanTransaction,
                    paymentInAdvance, transactionMappings, charges);
        }

        final LocalDate transactionDate = loanTransaction.getTransactionDate();
        final MonetaryCurrency currency = paymentInAdvance.getCurrency();
        Money transactionAmountRemaining = paymentInAdvance;

        final Money principalPortion = currentInstallment.payPrincipalComponent(transactionDate, transactionAmountRemaining);
        transactionAmountRemaining = transactionAmountRemaining.minus(principalPortion);
        final Money penaltyChargesPortion = currentInstallment.payPenaltyChargesComponent(transactionDate, transactionAmountRemaining);
        transactionAmountRemaining = transactionAmountRemaining.minus(penaltyChargesPortion);
        final Money feeChargesPortion = currentInstallment.payFeeChargesComponent(transactionDate, transactionAmountRemaining);
        transactionAmountRemaining = transactionAmountRemaining.minus(feeChargesPortion);
        final Money interestPortion = currentInstallment.payInterestComponent(transactionDate, transactionAmountRemaining);
        transactionAmountRemaining = transactionAmountRemaining.minus(interestPortion);

        loanTransaction.updateComponents(principalPortion, interestPortion, feeChargesPortion, penaltyChargesPortion);
        if (principalPortion.plus(interestPortion).plus(feeChargesPortion).plus(penaltyChargesPortion).isGreaterThanZero()) {
            transactionMappings.add(LoanTransactionToRepaymentScheduleMapping.createFrom(loanTransaction, currentInstallment,
                    principalPortion, interestPortion, feeChargesPortion, penaltyChargesPortion));
        }
        return transactionAmountRemaining;
    }
}
