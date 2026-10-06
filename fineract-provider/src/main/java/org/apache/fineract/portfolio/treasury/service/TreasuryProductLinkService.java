package org.apache.fineract.portfolio.treasury.service;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForSavings;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.data.LoanDTO;
import org.apache.fineract.accounting.journalentry.data.LoanTransactionDTO;
import org.apache.fineract.accounting.journalentry.data.SavingsDTO;
import org.apache.fineract.accounting.journalentry.data.SavingsTransactionDTO;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.portfolio.savings.DepositAccountType;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccount;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccountRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class TreasuryProductLinkService {

    private final TreasuryMovementService treasuryMovementService;
    private final TreasuryBankAccountRepository bankAccountRepository;
    private final AccountingProcessorHelper accountingProcessorHelper;
    private final SavingsAccountRepository savingsAccountRepository;

    @Transactional
    public void recordSavings(SavingsDTO savings) {
        if (savings == null || savings.getNewSavingsTransactions() == null) {
            return;
        }
        SavingsAccount account = savingsAccountRepository.findById(savings.getSavingsId()).orElse(null);
        if (account == null) {
            return;
        }
        DepositAccountType depositType = account.depositAccountType();
        for (SavingsTransactionDTO transaction : savings.getNewSavingsTransactions()) {
            if (transaction.isAccountTransfer() || transaction.isOverdraftTransaction() || transaction.getTransactionId() == null) {
                continue;
            }
            Long entityId = Long.valueOf(transaction.getTransactionId());
            String journalTransactionId = AccountingProcessorHelper.SAVINGS_TRANSACTION_IDENTIFIER + transaction.getTransactionId();
            if (transaction.isReversed()) {
                treasuryMovementService.reverseNative(TreasuryMovementService.LINK_SAVINGS, entityId);
                continue;
            }
            GLAccount fundSource = accountingProcessorHelper.getLinkedGLAccountForSavingsProduct(savings.getSavingsProductId(),
                    CashAccountsForSavings.SAVINGS_REFERENCE.getValue(), transaction.getPaymentTypeId());
            TreasuryBankAccount bank = bankFor(fundSource);
            if (bank == null) {
                continue;
            }
            if (transaction.getTransactionType().isDeposit() && (depositType.isSavingsDeposit() || depositType.isCurrentDeposit())) {
                treasuryMovementService.recordNative(TreasuryMovementService.TYPE_SAVINGS_DEPOSIT, TreasuryMovementService.DIRECTION_DEBIT,
                        bank.getId(), transaction.getOfficeId(), transaction.getAmount(), savings.getCurrencyCode(),
                        transaction.getTransactionDate(), journalTransactionId, TreasuryMovementService.LINK_SAVINGS, entityId,
                        "Savings deposit " + savings.getSavingsId());
            } else if (transaction.getTransactionType().isWithdrawal() && depositType.isFixedDeposit()) {
                treasuryMovementService.recordNative(TreasuryMovementService.TYPE_FD_PAYOUT, TreasuryMovementService.DIRECTION_CREDIT,
                        bank.getId(), transaction.getOfficeId(), transaction.getAmount(), savings.getCurrencyCode(),
                        transaction.getTransactionDate(), journalTransactionId, TreasuryMovementService.LINK_SAVINGS, entityId,
                        "Fixed deposit payout " + savings.getSavingsId());
            }
        }
    }

    @Transactional
    public void recordLoan(LoanDTO loan) {
        if (loan == null || loan.getNewLoanTransactions() == null) {
            return;
        }
        for (LoanTransactionDTO transaction : loan.getNewLoanTransactions()) {
            if (transaction.isAccountTransfer() || transaction.getTransactionId() == null || transaction.getTransactionType() == null
                    || !transaction.getTransactionType().isRepayment()) {
                continue;
            }
            Long entityId = Long.valueOf(transaction.getTransactionId());
            String journalTransactionId = AccountingProcessorHelper.LOAN_TRANSACTION_IDENTIFIER + transaction.getTransactionId();
            if (transaction.isReversed()) {
                treasuryMovementService.reverseNative(TreasuryMovementService.LINK_LOAN, entityId);
                continue;
            }
            GLAccount fundSource = accountingProcessorHelper.getLinkedGLAccountForLoanProduct(loan.getLoanProductId(),
                    CashAccountsForLoan.FUND_SOURCE.getValue(), transaction.getPaymentTypeId());
            TreasuryBankAccount bank = bankFor(fundSource);
            if (bank == null) {
                continue;
            }
            BigDecimal amount = transaction.getAmount();
            treasuryMovementService.recordNative(TreasuryMovementService.TYPE_LOAN_REPAYMENT, TreasuryMovementService.DIRECTION_DEBIT,
                    bank.getId(), transaction.getOfficeId(), amount, loan.getCurrencyCode(), transaction.getTransactionDate(),
                    journalTransactionId, TreasuryMovementService.LINK_LOAN, entityId, "Loan repayment " + loan.getLoanId());
        }
    }

    @Transactional(readOnly = true)
    public Map<String, Object> matchBank(String productType, Long productId, Long paymentTypeId) {
        if (productId == null) {
            return Map.of();
        }
        try {
            GLAccount fundSource = null;
            if ("loan".equals(productType)) {
                fundSource = accountingProcessorHelper.getLinkedGLAccountForLoanProduct(productId,
                        CashAccountsForLoan.FUND_SOURCE.getValue(), paymentTypeId);
            } else if ("savings".equals(productType)) {
                fundSource = accountingProcessorHelper.getLinkedGLAccountForSavingsProduct(productId,
                        CashAccountsForSavings.SAVINGS_REFERENCE.getValue(), paymentTypeId);
            }
            TreasuryBankAccount bank = bankFor(fundSource);
            if (bank == null) {
                return Map.of();
            }
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("id", bank.getId());
            data.put("name", bank.getName());
            data.put("currencyCode", bank.getCurrencyCode());
            data.put("glAccountId", bank.getGlAccount() == null ? null : bank.getGlAccount().getId());
            return data;
        } catch (RuntimeException ex) {
            return Map.of();
        }
    }

    private TreasuryBankAccount bankFor(GLAccount fundSource) {
        if (fundSource == null || fundSource.getId() == null) {
            return null;
        }
        return bankAccountRepository.findByGlAccountId(fundSource.getId()).filter(TreasuryBankAccount::isActive).orElse(null);
    }
}
