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
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionToRepaymentScheduleMapping;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.AbstractLoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.LoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanaccount.service.LoanBalanceService;

/**
 * Credesal horizontal {@link LoanRepaymentScheduleTransactionProcessor}.
 *
 * Allocates across installments by component type (not installment-first):
 * <ol>
 * <li>All due/overdue penalties (oldest installment first)</li>
 * <li>All due/overdue fees</li>
 * <li>All due/overdue interest</li>
 * <li>All due/overdue principal</li>
 * <li>Remainder on future installments in the same component order</li>
 * </ol>
 */
public class CredesalPenaltiesFeesInterestPrincipalLoanRepaymentScheduleTransactionProcessor
        extends AbstractLoanRepaymentScheduleTransactionProcessor {

    public static final String STRATEGY_CODE = "credesal-penalties-fees-interest-principal-strategy";

    public static final String STRATEGY_NAME = "Credesal Penalties, Fees, Interest, Principal (across installments)";

    public CredesalPenaltiesFeesInterestPrincipalLoanRepaymentScheduleTransactionProcessor(final ExternalIdFactory externalIdFactory,
            final LoanChargeValidator loanChargeValidator, final LoanBalanceService loanBalanceService) {
        super(externalIdFactory, loanChargeValidator, loanBalanceService);
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
    public boolean isInterestFirstRepaymentScheduleTransactionProcessor() {
        return true;
    }

    /**
     * Allocate the full payment once across the schedule (horizontal by component). Avoids Abstract's
     * installment-first loop, which would otherwise re-enter these hooks per period.
     */
    @Override
    protected Money processTransaction(final LoanTransaction loanTransaction, final MonetaryCurrency currency,
            final List<LoanRepaymentScheduleInstallment> installments, final Set<LoanCharge> charges, final Money amountToProcess) {
        Money transactionAmountUnprocessed = loanTransaction.getAmount(currency);
        if (amountToProcess != null) {
            transactionAmountUnprocessed = amountToProcess;
        }
        final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings = new ArrayList<>();

        if (loanTransaction.isChargesWaiver() || loanTransaction.isInterestWaiver() || loanTransaction.isChargePayment()) {
            // Waivers / charge payments stay installment-scoped via Abstract's walk.
            return super.processTransaction(loanTransaction, currency, installments, charges, amountToProcess);
        }

        transactionAmountUnprocessed = allocateHorizontally(installments, loanTransaction, transactionAmountUnprocessed,
                transactionMappings);
        loanTransaction.updateLoanTransactionToRepaymentScheduleMappings(transactionMappings);
        return transactionAmountUnprocessed;
    }

    @Override
    protected Money handleTransactionThatIsPaymentInAdvanceOfInstallment(final LoanRepaymentScheduleInstallment currentInstallment,
            final List<LoanRepaymentScheduleInstallment> installments, final LoanTransaction loanTransaction, final Money paymentInAdvance,
            final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings, final Set<LoanCharge> charges) {
        return allocateHorizontally(installments, loanTransaction, paymentInAdvance, transactionMappings);
    }

    @Override
    protected Money handleTransactionThatIsALateRepaymentOfInstallment(final LoanRepaymentScheduleInstallment currentInstallment,
            final List<LoanRepaymentScheduleInstallment> installments, final LoanTransaction loanTransaction,
            final Money transactionAmountUnprocessed, final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings,
            final Set<LoanCharge> charges) {
        return allocateHorizontally(installments, loanTransaction, transactionAmountUnprocessed, transactionMappings);
    }

    @Override
    protected Money handleTransactionThatIsOnTimePaymentOfInstallment(final LoanRepaymentScheduleInstallment currentInstallment,
            final LoanTransaction loanTransaction, final Money transactionAmountUnprocessed,
            final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings, final Set<LoanCharge> charges) {
        return allocateHorizontally(List.of(currentInstallment), loanTransaction, transactionAmountUnprocessed, transactionMappings);
    }

    private Money allocateHorizontally(final List<LoanRepaymentScheduleInstallment> installments, final LoanTransaction loanTransaction,
            final Money transactionAmountUnprocessed, final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings) {

        final LocalDate transactionDate = loanTransaction.getTransactionDate();
        Money transactionAmountRemaining = transactionAmountUnprocessed;

        // Pass 1–4 on installments due on or before transaction date, then same order on future installments.
        transactionAmountRemaining = applyComponentPasses(installments, loanTransaction, transactionDate, transactionAmountRemaining,
                transactionMappings, true);
        if (transactionAmountRemaining.isGreaterThanZero()) {
            transactionAmountRemaining = applyComponentPasses(installments, loanTransaction, transactionDate, transactionAmountRemaining,
                    transactionMappings, false);
        }
        return transactionAmountRemaining;
    }

    private Money applyComponentPasses(final List<LoanRepaymentScheduleInstallment> installments, final LoanTransaction loanTransaction,
            final LocalDate transactionDate, Money transactionAmountRemaining,
            final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings, final boolean dueOrOverdueOnly) {

        final MonetaryCurrency currency = transactionAmountRemaining.getCurrency();

        // Penalties
        for (final LoanRepaymentScheduleInstallment installment : installments) {
            if (!matchesPeriodBucket(installment, transactionDate, dueOrOverdueOnly) || !transactionAmountRemaining.isGreaterThanZero()) {
                continue;
            }
            if (!installment.getPenaltyChargesOutstanding(currency).isGreaterThanZero()) {
                continue;
            }
            final Money penaltyPortion = installment.payPenaltyChargesComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(penaltyPortion);
            if (penaltyPortion.isGreaterThanZero()) {
                loanTransaction.updateComponents(Money.zero(currency), Money.zero(currency), Money.zero(currency), penaltyPortion);
                addOrUpdateMapping(transactionMappings, loanTransaction, installment, Money.zero(currency), Money.zero(currency),
                        Money.zero(currency), penaltyPortion);
            }
        }

        // Fees
        for (final LoanRepaymentScheduleInstallment installment : installments) {
            if (!matchesPeriodBucket(installment, transactionDate, dueOrOverdueOnly) || !transactionAmountRemaining.isGreaterThanZero()) {
                continue;
            }
            if (!installment.getFeeChargesOutstanding(currency).isGreaterThanZero()) {
                continue;
            }
            final Money feePortion = installment.payFeeChargesComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(feePortion);
            if (feePortion.isGreaterThanZero()) {
                loanTransaction.updateComponents(Money.zero(currency), Money.zero(currency), feePortion, Money.zero(currency));
                addOrUpdateMapping(transactionMappings, loanTransaction, installment, Money.zero(currency), Money.zero(currency), feePortion,
                        Money.zero(currency));
            }
        }

        // Interest
        for (final LoanRepaymentScheduleInstallment installment : installments) {
            if (!matchesPeriodBucket(installment, transactionDate, dueOrOverdueOnly) || !transactionAmountRemaining.isGreaterThanZero()) {
                continue;
            }
            if (!installment.isInterestDue(currency)) {
                continue;
            }
            final Money interestPortion = installment.payInterestComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(interestPortion);
            if (interestPortion.isGreaterThanZero()) {
                loanTransaction.updateComponents(Money.zero(currency), interestPortion, Money.zero(currency), Money.zero(currency));
                addOrUpdateMapping(transactionMappings, loanTransaction, installment, Money.zero(currency), interestPortion,
                        Money.zero(currency), Money.zero(currency));
            }
        }

        // Principal
        for (final LoanRepaymentScheduleInstallment installment : installments) {
            if (!matchesPeriodBucket(installment, transactionDate, dueOrOverdueOnly) || !transactionAmountRemaining.isGreaterThanZero()) {
                continue;
            }
            if (!installment.isPrincipalNotCompleted(currency)) {
                continue;
            }
            final Money principalPortion = installment.payPrincipalComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(principalPortion);
            if (principalPortion.isGreaterThanZero()) {
                loanTransaction.updateComponents(principalPortion, Money.zero(currency), Money.zero(currency), Money.zero(currency));
                addOrUpdateMapping(transactionMappings, loanTransaction, installment, principalPortion, Money.zero(currency),
                        Money.zero(currency), Money.zero(currency));
            }
        }

        return transactionAmountRemaining;
    }

    private boolean matchesPeriodBucket(final LoanRepaymentScheduleInstallment installment, final LocalDate transactionDate,
            final boolean dueOrOverdueOnly) {
        final boolean dueOnOrBefore = !DateUtils.isAfter(installment.getDueDate(), transactionDate);
        return dueOrOverdueOnly ? dueOnOrBefore : !dueOnOrBefore;
    }

    private void addOrUpdateMapping(final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings,
            final LoanTransaction loanTransaction, final LoanRepaymentScheduleInstallment installment, final Money principalPortion,
            final Money interestPortion, final Money feePortion, final Money penaltyPortion) {
        for (final LoanTransactionToRepaymentScheduleMapping mapping : transactionMappings) {
            if (mapping.getLoanRepaymentScheduleInstallment().getDueDate().equals(installment.getDueDate())) {
                mapping.updateComponents(principalPortion, interestPortion, feePortion, penaltyPortion);
                return;
            }
        }
        transactionMappings.add(LoanTransactionToRepaymentScheduleMapping.createFrom(loanTransaction, installment, principalPortion,
                interestPortion, feePortion, penaltyPortion));
    }

    @Override
    protected Money handleRefundTransactionPaymentOfInstallment(final LoanRepaymentScheduleInstallment currentInstallment,
            final LoanTransaction loanTransaction, final Money transactionAmountUnprocessed,
            final List<LoanTransactionToRepaymentScheduleMapping> transactionMappings) {

        final LocalDate transactionDate = loanTransaction.getTransactionDate();
        Money transactionAmountRemaining = transactionAmountUnprocessed;
        Money principalPortion = Money.zero(transactionAmountRemaining.getCurrency());
        Money interestPortion = Money.zero(transactionAmountRemaining.getCurrency());
        Money feeChargesPortion = Money.zero(transactionAmountRemaining.getCurrency());
        Money penaltyChargesPortion = Money.zero(transactionAmountRemaining.getCurrency());

        if (transactionAmountRemaining.isGreaterThanZero()) {
            principalPortion = currentInstallment.unpayPrincipalComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(principalPortion);
        }
        if (transactionAmountRemaining.isGreaterThanZero()) {
            interestPortion = currentInstallment.unpayInterestComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(interestPortion);
        }
        if (transactionAmountRemaining.isGreaterThanZero()) {
            feeChargesPortion = currentInstallment.unpayFeeChargesComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(feeChargesPortion);
        }
        if (transactionAmountRemaining.isGreaterThanZero()) {
            penaltyChargesPortion = currentInstallment.unpayPenaltyChargesComponent(transactionDate, transactionAmountRemaining);
            transactionAmountRemaining = transactionAmountRemaining.minus(penaltyChargesPortion);
        }

        loanTransaction.updateComponents(principalPortion, interestPortion, feeChargesPortion, penaltyChargesPortion);
        if (principalPortion.plus(interestPortion).plus(feeChargesPortion).plus(penaltyChargesPortion).isGreaterThanZero()) {
            transactionMappings.add(LoanTransactionToRepaymentScheduleMapping.createFrom(loanTransaction, currentInstallment,
                    principalPortion, interestPortion, feeChargesPortion, penaltyChargesPortion));
        }
        return transactionAmountRemaining;
    }
}
