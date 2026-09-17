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
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidBy;
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
            materializeSourceExactDeclaredCharges(loanTransaction, currency, installments);
            return processSourceExactRepayment(loanTransaction, currency, installments, charges);
        }
        return super.processTransaction(loanTransaction, currency, installments, charges, amountToProcess);
    }

    @Override
    protected Money handleTransactionAndCharges(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments, final Set<LoanCharge> charges, final Money chargeAmountToProcess,
            final boolean isFeeCharge) {
        if (!loanTransaction.isSourceExactAllocation()) {
            return super.handleTransactionAndCharges(loanTransaction, currency, installments, charges, chargeAmountToProcess, isFeeCharge);
        }
        if (loanTransaction.isRepaymentLikeType() || loanTransaction.isInterestWaiver() || loanTransaction.isRecoveryRepayment()) {
            loanTransaction.resetDerivedComponents();
        }
        // Source-exact processing assigns its declared fee charge.
        // Generic fee post-processing would allocate the same fee a second time.
        // Penalties have no source charge identity, so preserve their standard paid-by bookkeeping.
        final Money transactionAmountUnprocessed = processTransaction(loanTransaction, currency, installments, charges,
                chargeAmountToProcess);
        if (loanTransaction.isNotWaiver() && !loanTransaction.isAccrual() && !loanTransaction.isAccrualActivity()) {
            final Money penaltyCharges = loanTransaction.getPenaltyChargesPortion(currency);
            if (penaltyCharges.isGreaterThanZero() && !loanTransaction.isSourceExactTransientChargeAllocation()) {
                updateChargesPaidAmountBy(loanTransaction, penaltyCharges, extractPenaltyCharges(charges), null);
            }
        }
        return transactionAmountUnprocessed;
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

    private void materializeSourceExactDeclaredCharges(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments) {
        final String feeChargeExternalId = loanTransaction.getSourceExactFeeChargeExternalId();
        final boolean hasNamedFeeCharge = feeChargeExternalId != null && !feeChargeExternalId.isBlank();
        if ((!loanTransaction.isSourceExactTransientChargeAllocation() && !hasNamedFeeCharge) || installments.isEmpty()) {
            return;
        }
        final Money requestedFee = loanTransaction.getSourceExactFeeChargesPortion(currency);
        final Money requestedPenalty = loanTransaction.getSourceExactPenaltyChargesPortion(currency);
        final Money representableFee = installments.stream().map(installment -> installment.getFeeChargesOutstanding(currency))
                .reduce(Money.zero(currency), Money::add);
        final Money representablePenalty = installments.stream().map(installment -> installment.getPenaltyChargesOutstanding(currency))
                .reduce(Money.zero(currency), Money::add);
        final Money missingFee = requestedFee.isGreaterThan(representableFee) ? requestedFee.minus(representableFee) : Money.zero(currency);
        final Money missingPenalty = requestedPenalty.isGreaterThan(representablePenalty) ? requestedPenalty.minus(representablePenalty)
                : Money.zero(currency);
        if (!missingFee.isGreaterThanZero() && !missingPenalty.isGreaterThanZero()) {
            return;
        }
        final LoanRepaymentScheduleInstallment installment = installments.stream()
                .filter(LoanRepaymentScheduleInstallment::isNotFullyPaidOff)
                .min((left, right) -> left.getDueDate().compareTo(right.getDueDate())).orElse(installments.getFirst());
        if (missingFee.isGreaterThanZero()) {
            installment.setFeeChargesCharged(installment.getFeeChargesCharged(currency).plus(missingFee).getAmount());
        }
        if (missingPenalty.isGreaterThanZero()) {
            installment.setPenaltyCharges(installment.getPenaltyChargesCharged(currency).plus(missingPenalty).getAmount());
        }
    }

    private Money processSourceExactRepayment(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments, final Set<LoanCharge> charges) {
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
        settleSourceExactFeeCharge(loanTransaction, currency, charges);
        if (principalRemaining.isGreaterThanZero() || interestRemaining.isGreaterThanZero() || feeRemaining.isGreaterThanZero()
                || penaltyRemaining.isGreaterThanZero()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.allocation.not.representable",
                    "The source-exact repayment allocation cannot be represented by the loan schedule. Remaining principal: %s, interest: %s, fees: %s, penalties: %s",
                    principalRemaining.getAmount(), interestRemaining.getAmount(), feeRemaining.getAmount(), penaltyRemaining.getAmount());
        }
        return Money.zero(currency);
    }

    private void settleSourceExactFeeCharge(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final Set<LoanCharge> charges) {
        final String externalId = loanTransaction.getSourceExactFeeChargeExternalId();
        if (externalId == null || externalId.isBlank()) {
            return; // Legacy source-exact transactions did not carry a charge identity.
        }
        final Money requested = loanTransaction.getSourceExactFeeChargesPortion(currency);
        if (!requested.isGreaterThanZero()) {
            // A replayed migration transaction can retain the historical charge identity even when its source-exact
            // fee component is zero. The identity has no financial effect in that case and must not block later events.
            return;
        }
        // Paid charges are inactive and are therefore absent from the active-charge set used by normal transaction
        // processing. Source-exact replay must still be able to find its persisted, named charge on the loan.
        final Set<LoanCharge> allLoanCharges = new HashSet<>(charges);
        if (loanTransaction.getLoan() != null && loanTransaction.getLoan().getLoanCharges() != null) {
            allLoanCharges.addAll(loanTransaction.getLoan().getLoanCharges());
        }
        final LoanCharge target = allLoanCharges.stream()
                .filter(charge -> charge.getExternalId() != null && externalId.equals(charge.getExternalId().getValue())).findFirst()
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.fee.charge.missing",
                        "The declared source-exact fee charge does not exist on this loan: " + externalId));
        final String transactionExternalId = loanTransaction.getExternalId() == null ? null : loanTransaction.getExternalId().getValue();
        final LoanChargePaidBy existingOwner = target.getLoanChargePaidBySet().stream().filter(mapping -> {
            final LoanTransaction ownerTransaction = mapping.getLoanTransaction();
            if (ownerTransaction == null) {
                return false;
            }
            if (ownerTransaction.equals(loanTransaction)) {
                return true;
            }
            return transactionExternalId != null && ownerTransaction.getExternalId() != null
                    && transactionExternalId.equals(ownerTransaction.getExternalId().getValue());
        }).findFirst().orElse(null);
        if (existingOwner != null) {
            final Money existingPaid = Money.of(currency, existingOwner.getAmount());
            final boolean hasConflictingOwner = target.getLoanChargePaidBySet().stream().anyMatch(mapping -> {
                if (mapping == existingOwner || mapping.getAmount().signum() <= 0) {
                    return false;
                }
                final LoanTransaction ownerTransaction = mapping.getLoanTransaction();
                // Accrual and accrual-adjustment rows reuse m_loan_charge_paid_by to retain accounting
                // attribution. They are not customer payments and therefore do not compete with the
                // source-exact repayment that owns the historical fee charge.
                return ownerTransaction == null || (!ownerTransaction.isAccrual() && !ownerTransaction.isAccrualAdjustment());
            });
            if (!existingPaid.isEqualTo(requested) || hasConflictingOwner) {
                throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.fee.charge.not.representable",
                        "The declared source-exact fee charge has an incompatible existing payment owner");
            }
            // Adding the next historical charge retains the exact earlier owner row while replay resets the charge's
            // derived paid amount. Restore that amount, then reattach ownership to the transaction being rebuilt.
            target.updatePaidAmountBy(requested, null, requested.zero());
            if (!target.getAmountPaid(currency).isEqualTo(requested) || !target.getAmountOutstanding(currency).isZero()) {
                throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.fee.charge.not.representable",
                        "The declared source-exact fee charge cannot restore its existing payment owner");
            }
            loanTransaction.updateLoanChargePaidMappings(List.of(existingOwner));
            return;
        }
        Money paid = target.updatePaidAmountBy(requested, null, requested.zero());
        if (!paid.isEqualTo(requested) && target.getLoanChargePaidBySet().isEmpty() && target.getAmountPaid(currency).isEqualTo(requested)
                && target.getAmountOutstanding(currency).isZero()) {
            // Adding a historical charge reprocesses the loan. Fineract can derive the charge as paid from an earlier
            // schedule-level fee without creating a charge-paid-by owner. Reclaim only that exact orphaned state so the
            // source transaction named by feeChargeExternalId becomes the authoritative owner.
            target.resetPaidAmount(currency);
            paid = target.updatePaidAmountBy(requested, null, requested.zero());
        }
        if (!paid.isEqualTo(requested)) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.source.exact.fee.charge.not.representable",
                    "The declared source-exact fee charge cannot receive the requested fee allocation");
        }
        loanTransaction.updateLoanChargePaidMappings(List.of(new LoanChargePaidBy(loanTransaction, target, paid.getAmount(), null)));
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
