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
package org.apache.fineract.portfolio.loanaccount.service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.portfolio.account.PortfolioAccountType;
import org.apache.fineract.portfolio.account.data.AccountTransferDTO;
import org.apache.fineract.portfolio.account.domain.AccountTransferAssembler;
import org.apache.fineract.portfolio.account.domain.AccountTransferDetailRepository;
import org.apache.fineract.portfolio.account.domain.AccountTransferDetails;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanAccountDomainService;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionType;
import org.springframework.stereotype.Service;

/** Internal, same-loan transfer of retained refinancing proceeds; never a borrower cash receipt. */
@Service
@RequiredArgsConstructor
public class LoanRefinancingSurplusService {

    private static final String DESCRIPTION = "Refinancing surplus repayment";
    private final LoanAccountDomainService loanAccountDomainService;
    private final LoanTransactionRepository loanTransactionRepository;
    private final LoanJournalEntryPoster journalEntryPoster;
    private final AccountTransferAssembler accountTransferAssembler;
    private final AccountTransferDetailRepository accountTransferDetailRepository;

    public static boolean isEligible(final Loan loan) {
        return loan.isTopup() && loan.getClientId() != null && !loan.isMultiDisburmentLoan()
                && !loan.getLoanProductRelatedDetail().isEnableDownPayment()
                && loan.getActiveCharges().stream()
                        .noneMatch(charge -> (charge.isDueAtDisbursement()
                                || (charge.getChargeTimeType() != null && charge.getChargeTimeType().isAvailableAtCashier()))
                                && charge.getChargePaymentMode().isPaymentModeAccountTransfer());
    }

    public void validateRequest(final Loan loan, final boolean requested, final boolean sourceExact) {
        if (requested && (sourceExact || !isEligible(loan))) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.refinancing.surplus.repayment.not.supported",
                    "Retained proceeds require ordinary single-disbursement refinancing without down payments or savings-paid disbursement charges");
        }
    }

    public Money repaymentAmount(final Money remainderAfterPayoff, final BigDecimal disbursementCharges) {
        final Money amount = remainderAfterPayoff.minus(disbursementCharges);
        if (amount.isLessThanZero()) {
            throw new GeneralPlatformDomainRuleException("error.msg.loan.refinancing.surplus.insufficient.for.charges",
                    "The refinancing remainder must cover all disbursement charges before a repayment can be retained");
        }
        return amount;
    }

    // Created before schedule finalization so total principal disbursed still includes all proceeds.
    public LoanTransaction createDisbursement(final Loan loan, final Money amount, final LocalDate date, final ExternalId externalId) {
        if (!amount.isGreaterThanZero()) {
            return null;
        }
        final LoanTransaction transaction = LoanTransaction.disbursement(loan, amount, null, date, externalId,
                loan.getTotalOverpaidAsMoney());
        transaction.updateLoan(loan);
        loan.addLoanTransaction(transaction);
        loanTransactionRepository.saveAndFlush(transaction);
        journalEntryPoster.postJournalEntriesForLoanTransaction(transaction, true, true);
        return transaction;
    }

    // Called only after the loan is active and disbursement charges have been paid, in the disbursement transaction.
    public LoanTransaction applyRepayment(final Loan loan, final LoanTransaction disbursement, final Money amount, final LocalDate date,
            final Locale locale, final DateTimeFormatter dateFormat) {
        if (disbursement == null) {
            return null;
        }
        final LoanTransaction repayment = loanAccountDomainService.makeRepayment(LoanTransactionType.REPAYMENT, loan, date,
                amount.getAmount(), null, DESCRIPTION, ExternalId.generate(), false, null, true, null, false, true);
        final AccountTransferDTO transfer = new AccountTransferDTO(date, amount.getAmount(), PortfolioAccountType.LOAN,
                PortfolioAccountType.LOAN, loan.getId(), loan.getId(), DESCRIPTION, locale, dateFormat,
                LoanTransactionType.DISBURSEMENT.getValue(), LoanTransactionType.REPAYMENT.getValue(), disbursement.getExternalId(), loan,
                loan);
        final AccountTransferDetails details = accountTransferAssembler.assembleLoanToLoanTransfer(transfer, loan, loan, disbursement,
                repayment);
        accountTransferDetailRepository.saveAndFlush(details);
        return repayment;
    }
}
