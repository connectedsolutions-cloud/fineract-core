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
package org.apache.fineract.portfolio.shareaccounts.service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForShares;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.accounting.journalentry.service.JournalEntryWritePlatformService;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.organisation.teller.domain.CashierTxnType;
import org.apache.fineract.organisation.teller.exception.CashierNotFoundException;
import org.apache.fineract.portfolio.paymentdetail.domain.PaymentDetail;
import org.apache.fineract.portfolio.paymentdetail.domain.PaymentDetailRepository;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccount;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountRepositoryWrapper;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountStatusType;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountTransaction;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificate;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificateRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ShareAccountPaymentService {

    public static final String SHARE_ACCOUNT_ENTITY = "share account";

    private final ShareAccountRepositoryWrapper shareAccountRepository;
    private final PaymentDetailRepository paymentDetailRepository;
    private final CashierRepository cashierRepository;
    private final CashierTransactionRepository cashierTransactionRepository;
    private final AccountingProcessorHelper accountingProcessorHelper;
    private final AccountingCutoffPolicyService cutoffPolicyService;
    private final JournalEntryWritePlatformService journalEntryWritePlatformService;
    private final ShareCertificateService shareCertificateService;
    private final ShareCertificateRepository shareCertificateRepository;
    private final PlatformSecurityContext platformSecurityContext;

    @Transactional
    public CommandProcessingResult recordChannelPayment(final Long accountId, final LocalDate transactionDate,
            final PaymentDetail paymentDetail) {
        if (paymentDetail == null || paymentDetail.getPaymentType() == null) {
            throw rule("error.msg.share.account.payment.type.required", "A cheque or bank transfer payment type is required");
        }
        if (Boolean.TRUE.equals(paymentDetail.getPaymentType().getIsCashPayment())) {
            throw rule("error.msg.share.account.cash.payment.requires.teller",
                    "Cash payments must be recorded at the teller");
        }
        if (StringUtils.isBlank(paymentDetail.getCheckNumber()) && StringUtils.isBlank(paymentDetail.getAccountNumber())
                && StringUtils.isBlank(paymentDetail.getBankNumber()) && StringUtils.isBlank(paymentDetail.getReceiptNumber())) {
            throw rule("error.msg.share.account.payment.details.required",
                    "Cheque number or bank transfer details are required");
        }
        final ShareAccount account = approvedAccount(accountId);
        final List<ShareAccountTransaction> purchases = approvedPurchases(account);
        final PaymentDetail saved = this.paymentDetailRepository.save(paymentDetail);
        for (final ShareAccountTransaction purchase : purchases) {
            purchase.setPaymentDetail(saved);
        }
        postFunding(account, purchases, transactionDate, saved, false);
        return activate(account, transactionDate);
    }

    @Transactional
    public CommandProcessingResult recordCashierPayment(final Long accountId, final LocalDate transactionDate, final Long cashierId,
            final String note) {
        final ShareAccount account = approvedAccount(accountId);
        final List<ShareAccountTransaction> purchases = approvedPurchases(account);
        final Cashier cashier = this.cashierRepository.findById(cashierId).orElseThrow(() -> new CashierNotFoundException(cashierId));
        if (cashier.getTeller() == null || cashier.getTeller().getOffice() == null
                || !cashier.getTeller().getOffice().getId().equals(account.getOfficeId())) {
            throw rule("error.msg.share.account.cashier.office.mismatch",
                    "The cashier office must match the share account office");
        }
        final BigDecimal amount = purchaseAmount(purchases);
        final CashierTransaction cashierTransaction = CashierTransaction.createBalanceTransaction(cashier,
                CashierTxnType.INWARD_CASH_TXN.getId(), amount, transactionDate, account.getCurrency().getCode(),
                StringUtils.defaultIfBlank(note, "Share certificate cash collection"));
        cashierTransaction.setEntityType(SHARE_ACCOUNT_ENTITY);
        cashierTransaction.setEntityId(accountId);
        final CashierTransaction saved = this.cashierTransactionRepository.saveAndFlush(cashierTransaction);
        for (final ShareAccountTransaction purchase : purchases) {
            purchase.setCashierTransactionId(saved.getId());
        }
        postFunding(account, purchases, transactionDate, null, true);
        return activate(account, transactionDate);
    }

    @Transactional
    public CommandProcessingResult undoPayment(final Long accountId, final LocalDate transactionDate) {
        final ShareAccount account = this.shareAccountRepository.findOneWithNotFoundDetection(accountId);
        if (!ShareAccountStatusType.ACTIVE.getValue().equals(account.status())) {
            throw rule("error.msg.share.account.undo.payment.not.active", "Only an active share account can have its payment undone");
        }
        final List<ShareAccountTransaction> purchases = new ArrayList<>();
        for (final ShareAccountTransaction transaction : account.getShareAccountTransactions()) {
            if (!transaction.isActive()) {
                continue;
            }
            if (transaction.isRedeemTransaction()) {
                throw rule("error.msg.share.account.undo.payment.redeemed",
                        "Payment cannot be undone after shares have been redeemed");
            }
            if (transaction.isPurchasTransaction()) {
                purchases.add(transaction);
            }
        }
        if (purchases.isEmpty()) {
            throw rule("error.msg.share.account.payment.without.purchase", "The share account has no approved purchase to pay");
        }
        for (final ShareAccountTransaction purchase : purchases) {
            if (purchase.getPaymentDetail() == null && purchase.getCashierTransactionId() == null) {
                throw rule("error.msg.share.account.undo.payment.later.purchase",
                        "Payment cannot be undone after another share purchase has been approved");
            }
        }
        this.shareCertificateService.reopenUnprinted(accountId);
        final ArrayList<Long> journalTransactions = new ArrayList<>();
        Long cashierTransactionId = null;
        BigDecimal cashierAmount = BigDecimal.ZERO;
        for (final ShareAccountTransaction purchase : purchases) {
            journalTransactions.add(purchase.getId());
            if (purchase.getCashierTransactionId() != null) {
                cashierTransactionId = purchase.getCashierTransactionId();
                cashierAmount = cashierAmount.add(purchase.amount());
            }
            purchase.clearRecordedPayment();
        }
        for (final ShareAccountTransaction charge : account.getChargeTransactions()) {
            journalTransactions.add(charge.getId());
        }
        this.journalEntryWritePlatformService.revertShareAccountJournalEntries(journalTransactions, transactionDate);
        if (cashierTransactionId != null) {
            final Long originalCashierTransactionId = cashierTransactionId;
            final CashierTransaction original = this.cashierTransactionRepository.findById(originalCashierTransactionId)
                    .orElseThrow(() -> new CashierNotFoundException(originalCashierTransactionId));
            final CashierTransaction reversal = CashierTransaction.createBalanceTransaction(original.getCashier(),
                    CashierTxnType.OUTWARD_CASH_TXN.getId(), cashierAmount, transactionDate, account.getCurrency().getCode(),
                    "Reversal of share certificate cash collection");
            reversal.setEntityType(SHARE_ACCOUNT_ENTITY);
            reversal.setEntityId(accountId);
            this.cashierTransactionRepository.save(reversal);
        }
        account.undoActivation();
        this.shareAccountRepository.save(account);
        return new CommandProcessingResultBuilder().withEntityId(accountId).withClientId(account.getClientId()).build();
    }

    private ShareAccount approvedAccount(final Long accountId) {
        final ShareAccount account = this.shareAccountRepository.findOneWithNotFoundDetection(accountId);
        if (!ShareAccountStatusType.APPROVED.getValue().equals(account.status())) {
            throw rule("error.msg.share.account.payment.requires.approval",
                    "Share account payment is allowed only after approval");
        }
        return account;
    }

    private List<ShareAccountTransaction> approvedPurchases(final ShareAccount account) {
        final List<ShareAccountTransaction> purchases = new ArrayList<>();
        for (final ShareAccountTransaction transaction : account.getShareAccountTransactions()) {
            if (transaction.isActive() && transaction.isPurchasTransaction()) {
                if (transaction.getPaymentDetail() != null || transaction.getCashierTransactionId() != null) {
                    throw rule("error.msg.share.account.already.paid", "This share account already has a recorded payment");
                }
                purchases.add(transaction);
            }
        }
        if (purchases.isEmpty()) {
            throw rule("error.msg.share.account.payment.without.purchase", "The share account has no approved purchase to pay");
        }
        if (purchaseAmount(purchases).compareTo(BigDecimal.ZERO) <= 0) {
            throw rule("error.msg.share.account.payment.amount.invalid", "The approved share purchase amount must be greater than zero");
        }
        return purchases;
    }

    private void postFunding(final ShareAccount account, final List<ShareAccountTransaction> purchases, final LocalDate transactionDate,
            final PaymentDetail paymentDetail, final boolean cashierCash) {
        if (!Integer.valueOf(2).equals(account.getShareProduct().getAccountingType())
                || !this.cutoffPolicyService.shouldGenerateAccounting(transactionDate)) {
            return;
        }
        final Office office = this.accountingProcessorHelper.getOfficeById(account.getOfficeId());
        final Long paymentTypeId = paymentDetail == null ? null : paymentDetail.getPaymentType().getId();
        final GLAccount debitAccount = cashierCash ? this.accountingProcessorHelper.getCashAtTellerGLAccount()
                : this.accountingProcessorHelper.getShareProductGLAccount(account.getShareProduct().getId(),
                        CashAccountsForShares.SHARES_REFERENCE.getValue(), paymentTypeId);
        final GLAccount equity = this.accountingProcessorHelper.getShareProductGLAccount(account.getShareProduct().getId(),
                CashAccountsForShares.SHARES_EQUITY.getValue(), null);
        for (final ShareAccountTransaction purchase : purchases) {
            this.accountingProcessorHelper.createShareFundingJournalEntry(office, account.getCurrency().getCode(), debitAccount, equity,
                    account.getId(), purchase.getId().toString(), transactionDate, purchase.amount(), paymentDetail);
        }
    }

    private CommandProcessingResult activate(final ShareAccount account, final LocalDate transactionDate) {
        account.activate(transactionDate, this.platformSecurityContext.authenticatedUser());
        this.shareAccountRepository.saveAndFlush(account);
        for (final ShareCertificate certificate : this.shareCertificateRepository.findByShareAccountIdOrderByIdAsc(account.getId())) {
            if (ShareCertificate.STATUS_OPENED.equals(certificate.getNativeStatus())) {
                this.shareCertificateService.emit(certificate.getId());
            }
        }
        return new CommandProcessingResultBuilder().withEntityId(account.getId()).withClientId(account.getClientId()).build();
    }

    private static BigDecimal purchaseAmount(final List<ShareAccountTransaction> purchases) {
        BigDecimal amount = BigDecimal.ZERO;
        for (final ShareAccountTransaction purchase : purchases) {
            if (purchase.amount() != null) {
                amount = amount.add(purchase.amount());
            }
        }
        return amount;
    }

    private static GeneralPlatformDomainRuleException rule(final String code, final String message) {
        return new GeneralPlatformDomainRuleException(code, message);
    }
}
