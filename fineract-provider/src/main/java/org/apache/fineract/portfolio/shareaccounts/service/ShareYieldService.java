/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForShares;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccountType;
import org.apache.fineract.accounting.journalentry.service.JournalEntryWritePlatformService;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMapping;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMappingRepository;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.portfolio.PortfolioProductType;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransaction;
import org.apache.fineract.portfolio.savings.service.SavingsAccountDomainService;
import org.apache.fineract.portfolio.shareaccounts.data.ShareAccountTransactionEnumData;
import org.apache.fineract.portfolio.shareaccounts.domain.PurchasedSharesStatusType;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccount;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountRepository;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountRepositoryWrapper;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountStatusType;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountTransaction;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountYieldAccrual;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountYieldAccrualRepository;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountYieldSettlement;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountYieldSettlementRepository;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareProductYieldConfiguration;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareProductYieldConfigurationRepository;
import org.apache.fineract.portfolio.shareproducts.domain.ShareProduct;
import org.apache.fineract.portfolio.shareproducts.domain.ShareProductRepositoryWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ShareYieldService {

    private static final String ENTRY_ACCRUAL = "ACCRUAL";
    private static final String ENTRY_OPENING = "OPENING";

    private final ShareProductYieldConfigurationRepository configurationRepository;
    private final ShareAccountYieldAccrualRepository accrualRepository;
    private final ShareAccountYieldSettlementRepository settlementRepository;
    private final ShareAccountRepository shareAccountRepository;
    private final ShareAccountRepositoryWrapper shareAccountRepositoryWrapper;
    private final ShareProductRepositoryWrapper shareProductRepositoryWrapper;
    private final GLAccountRepositoryWrapper glAccountRepositoryWrapper;
    private final ProductToGLAccountMappingRepository productMappingRepository;
    private final JournalEntryWritePlatformService journalEntryWritePlatformService;
    private final AccountingCutoffPolicyService cutoffPolicyService;
    private final SavingsAccountDomainService savingsAccountDomainService;
    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepositoryWrapper;

    @Transactional
    public CommandProcessingResult configureProduct(Long productId, JsonCommand command) {
        ShareProduct product = shareProductRepositoryWrapper.findOneWithNotFoundDetection(productId);
        boolean enabled = command.booleanPrimitiveValueOfParameterNamed("enabled");
        BigDecimal annualRate = requiredPositive(command.bigDecimalValueOfParameterNamed("annualRate"), "annualRate");
        LocalDate startDate = required(command.localDateValueOfParameterNamed("accrualStartDate"), "accrualStartDate");
        GLAccount expense = glAccountRepositoryWrapper
                .findOneWithNotFoundDetection(required(command.longValueOfParameterNamed("expenseAccountId"), "expenseAccountId"));
        GLAccount payable = glAccountRepositoryWrapper
                .findOneWithNotFoundDetection(required(command.longValueOfParameterNamed("payableAccountId"), "payableAccountId"));
        requireAccountType(expense, GLAccountType.EXPENSE, "expenseAccountId");
        requireAccountType(payable, GLAccountType.LIABILITY, "payableAccountId");

        ShareProductYieldConfiguration config = configurationRepository.findById(productId)
                .orElseGet(() -> new ShareProductYieldConfiguration(product, enabled, annualRate, startDate, expense, payable));
        config.update(enabled, annualRate, startDate, expense, payable);
        configurationRepository.save(config);
        upsertMapping(productId, CashAccountsForShares.YIELD_EXPENSE.getValue(), expense);
        upsertMapping(productId, CashAccountsForShares.YIELD_PAYABLE.getValue(), payable);

        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(productId).build();
    }

    @Transactional
    public CommandProcessingResult importAccrual(Long accountId, JsonCommand command) {
        ShareAccount account = shareAccountRepositoryWrapper.findOneWithNotFoundDetection(accountId);
        LocalDate date = required(command.localDateValueOfParameterNamed("accrualDate"), "accrualDate");
        String entryType = command.stringValueOfParameterNamed("entryType");
        entryType = entryType == null ? ENTRY_ACCRUAL : entryType.trim().toUpperCase();
        if (!ENTRY_ACCRUAL.equals(entryType) && !ENTRY_OPENING.equals(entryType)) {
            throw validation("entryType", "entryType must be ACCRUAL or OPENING");
        }
        BigDecimal baseAmount = requiredNonNegative(command.bigDecimalValueOfParameterNamed("baseAmount"), "baseAmount");
        BigDecimal annualRate = requiredNonNegative(command.bigDecimalValueOfParameterNamed("annualRate"), "annualRate");
        Integer dayCountBasis = required(command.integerValueSansLocaleOfParameterNamed("dayCountBasis"), "dayCountBasis");
        BigDecimal accruedAmount = requiredNonNegative(command.bigDecimalValueOfParameterNamed("accruedAmount"), "accruedAmount")
                .setScale(8, RoundingMode.HALF_UP);
        BigDecimal bookedAmount = requiredNonNegative(command.bigDecimalValueOfParameterNamed("bookedAmount"), "bookedAmount")
                .setScale(account.getCurrency().getDigitsAfterDecimal(), RoundingMode.HALF_UP);
        String sourceReference = requiredText(command.stringValueOfParameterNamed("sourceReference"), "sourceReference");

        var byReference = accrualRepository.findBySourceReference(sourceReference);
        if (byReference.isPresent()) {
            ShareAccountYieldAccrual existing = byReference.get();
            requireSame(existing, accountId, date, accruedAmount, bookedAmount);
            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(accountId)
                    .withSubEntityId(existing.getId()).build();
        }
        if (ENTRY_ACCRUAL.equals(entryType)) {
            validateFormula(baseAmount, annualRate, dayCountBasis, accruedAmount);
        }
        ShareAccountYieldAccrual saved = createAccrual(account, date, entryType, baseAmount, annualRate, dayCountBasis, accruedAmount,
                bookedAmount, sourceReference, true);
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(accountId)
                .withSubEntityId(saved.getId()).build();
    }

    @Transactional
    public void accrueThrough(LocalDate tillDate) {
        for (ShareProductYieldConfiguration config : configurationRepository.findByEnabledTrue()) {
            for (ShareAccount account : shareAccountRepository.findAll()) {
                if (!account.getShareProduct().getId().equals(config.getProductId())
                        || !ShareAccountStatusType.fromInt(account.status()).isActive() || account.getTotalApprovedShares() == null
                        || account.getTotalApprovedShares() <= 0) {
                    continue;
                }
                LocalDate latest = accrualRepository.findLatestAccrualDate(account.getId());
                LocalDate next = latest == null ? later(config.getAccrualStartDate(), account.getActivatedDate()) : latest.plusDays(1);
                while (!next.isAfter(tillDate)) {
                    if (accrualRepository.existsByShareAccountIdAndAccrualDate(account.getId(), next)) {
                        next = next.plusDays(1);
                        continue;
                    }
                    int basis = ShareYieldCalculator.actualYearBasis(next);
                    BigDecimal base = account.getShareProduct().getUnitPrice()
                            .multiply(BigDecimal.valueOf(account.getTotalApprovedShares()));
                    BigDecimal exact = ShareYieldCalculator.dailyAccrual(base, config.getAnnualRate(), basis);
                    BigDecimal booked = exact.setScale(account.getCurrency().getDigitsAfterDecimal(), RoundingMode.HALF_UP);
                    createAccrual(account, next, ENTRY_ACCRUAL, base, config.getAnnualRate(), basis, exact, booked, null, false);
                    next = next.plusDays(1);
                }
            }
        }
    }

    @Transactional
    public CommandProcessingResult settle(Long accountId, JsonCommand command) {
        shareAccountRepositoryWrapper.findOneWithNotFoundDetection(accountId);
        ShareAccount account = settlementRepository.lockShareAccount(accountId)
                .orElseThrow(() -> validation("accountId", "Share account does not exist"));
        LocalDate date = required(command.localDateValueOfParameterNamed("transactionDate"), "transactionDate");
        BigDecimal amount = requiredPositive(command.bigDecimalValueOfParameterNamed("amount"), "amount")
                .setScale(account.getCurrency().getDigitsAfterDecimal(), RoundingMode.HALF_UP);
        String reference = requiredText(command.stringValueOfParameterNamed("reference"), "reference");
        var existing = settlementRepository.findByReference(reference);
        if (existing.isPresent()) {
            ShareAccountYieldSettlement settlement = existing.get();
            if (!settlement.getShareAccount().getId().equals(accountId) || settlement.getAmount().compareTo(amount) != 0
                    || !settlement.getSettlementDate().equals(date)) {
                throw validation("reference", "Settlement reference already exists with different financial details");
            }
            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(accountId)
                    .withSubEntityId(settlement.getId()).build();
        }
        BigDecimal outstanding = outstanding(accountId);
        if (amount.compareTo(outstanding) > 0) {
            throw validation("amount", "Settlement amount exceeds unpaid accrued share yield");
        }
        Long payableId = configurationRepository.findById(account.getShareProduct().getId())
                .orElseThrow(() -> validation("productId", "Share product has no yield configuration")).getPayableAccount().getId();
        Long activityPayableId = financialActivityAccountRepositoryWrapper
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.PAYABLE_DIVIDENDS.getValue()).getGlAccount().getId();
        if (!payableId.equals(activityPayableId)) {
            throw validation("payableAccountId", "Share yield payable must match financial activity PAYABLE_DIVIDENDS before settlement");
        }
        if (account.getSavingsAccount() == null) {
            throw validation("savingsAccountId", "Share account must have a linked savings account before yield settlement");
        }
        SavingsAccountTransaction savingsTransaction = savingsAccountDomainService.handleDividendPayout(account.getSavingsAccount(), date,
                amount, false);
        ShareAccountYieldSettlement saved = settlementRepository
                .save(new ShareAccountYieldSettlement(account, savingsTransaction, date, amount, reference));
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(accountId)
                .withSubEntityId(saved.getId()).withTransactionId(savingsTransaction.getId().toString()).build();
    }

    @Transactional(readOnly = true)
    public Map<String, Object> retrieveProductConfiguration(Long productId) {
        ShareProductYieldConfiguration c = configurationRepository.findById(productId)
                .orElseThrow(() -> validation("productId", "Share product has no yield configuration"));
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("productId", c.getProductId());
        data.put("enabled", c.isEnabled());
        data.put("annualRate", c.getAnnualRate());
        data.put("accrualStartDate", c.getAccrualStartDate());
        data.put("expenseAccountId", c.getExpenseAccount().getId());
        data.put("payableAccountId", c.getPayableAccount().getId());
        data.put("dayCountConvention", "ACTUAL_ACTUAL");
        return data;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> retrieveAccountYield(Long accountId) {
        shareAccountRepositoryWrapper.findOneWithNotFoundDetection(accountId);
        List<Map<String, Object>> entries = new ArrayList<>();
        for (ShareAccountYieldAccrual a : accrualRepository.findByShareAccountIdOrderByAccrualDateAscIdAsc(accountId)) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", a.getId());
            row.put("date", a.getAccrualDate());
            row.put("entryType", a.getEntryType());
            row.put("baseAmount", a.getBaseAmount());
            row.put("annualRate", a.getAnnualRate());
            row.put("dayCountBasis", a.getDayCountBasis());
            row.put("accruedAmount", a.getAccruedAmount());
            row.put("bookedAmount", a.getBookedAmount());
            row.put("sourceReference", a.getSourceReference());
            row.put("imported", a.isImported());
            entries.add(row);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("shareAccountId", accountId);
        result.put("accrued", accrualRepository.sumBookedAmount(accountId));
        result.put("settled", settlementRepository.sumSettledAmount(accountId));
        result.put("outstanding", outstanding(accountId));
        result.put("accruals", entries);
        return result;
    }

    private ShareAccountYieldAccrual createAccrual(ShareAccount account, LocalDate date, String entryType, BigDecimal base, BigDecimal rate,
            int basis, BigDecimal exact, BigDecimal booked, String sourceReference, boolean imported) {
        ShareAccountTransaction transaction = ShareAccountTransaction.createYieldAccrualTransaction(date, booked);
        account.addYieldAccrualTransaction(transaction);
        shareAccountRepository.saveAndFlush(account);
        ShareAccountYieldAccrual accrual = accrualRepository.saveAndFlush(new ShareAccountYieldAccrual(account, transaction, date,
                entryType, base, rate, basis, exact, booked, sourceReference, imported));
        if (booked.signum() > 0 && cutoffPolicyService.shouldGenerateAccounting(date)) {
            journalEntryWritePlatformService.createJournalEntriesForShares(accountingBridge(account, transaction));
        }
        return accrual;
    }

    private Map<String, Object> accountingBridge(ShareAccount account, ShareAccountTransaction transaction) {
        Map<String, Object> bridge = new HashMap<>();
        bridge.put("shareAccountId", account.getId());
        bridge.put("shareProductId", account.getShareProduct().getId());
        bridge.put("officeId", account.getOfficeId());
        bridge.put("currencyCode", account.getCurrency().getCode());
        Map<String, Object> tx = new HashMap<>();
        tx.put("officeId", account.getOfficeId());
        tx.put("id", transaction.getId());
        tx.put("date", transaction.getPurchasedDate());
        tx.put("status", new ShareAccountTransactionEnumData(PurchasedSharesStatusType.APPROVED.getValue().longValue(), null, null));
        tx.put("type", new ShareAccountTransactionEnumData(PurchasedSharesStatusType.YIELD_ACCRUAL.getValue().longValue(), null, null));
        tx.put("amount", transaction.amount());
        tx.put("chargeAmount", null);
        tx.put("paymentTypeId", null);
        bridge.put("newTransactions", List.of(tx));
        return bridge;
    }

    private void upsertMapping(Long productId, int financialAccountType, GLAccount glAccount) {
        ProductToGLAccountMapping mapping = productMappingRepository.findCoreProductToFinAccountMapping(productId,
                PortfolioProductType.SHARES.getValue(), financialAccountType);
        if (mapping == null) {
            mapping = ProductToGLAccountMapping.createNew(glAccount, productId, PortfolioProductType.SHARES.getValue(),
                    financialAccountType, null, null, null);
        } else {
            mapping.setGlAccount(glAccount);
        }
        productMappingRepository.save(mapping);
    }

    private BigDecimal outstanding(Long accountId) {
        return accrualRepository.sumBookedAmount(accountId).subtract(settlementRepository.sumSettledAmount(accountId));
    }

    private static void validateFormula(BigDecimal base, BigDecimal rate, int basis, BigDecimal exact) {
        if (basis != 365 && basis != 366) {
            throw validation("dayCountBasis", "dayCountBasis must be 365 or 366");
        }
        if (ShareYieldCalculator.dailyAccrual(base, rate, basis).compareTo(exact) != 0) {
            throw validation("accruedAmount", "accruedAmount does not equal baseAmount × annualRate / (100 × dayCountBasis)");
        }
    }

    private static LocalDate later(LocalDate first, LocalDate second) {
        return first.isAfter(second) ? first : second;
    }

    private static void requireSame(ShareAccountYieldAccrual existing, Long accountId, LocalDate date, BigDecimal exact,
            BigDecimal booked) {
        if (!existing.getShareAccount().getId().equals(accountId) || !existing.getAccrualDate().equals(date)
                || existing.getAccruedAmount().compareTo(exact) != 0 || existing.getBookedAmount().compareTo(booked) != 0) {
            throw validation("sourceReference", "Source reference already exists with different financial details");
        }
    }

    private static void requireAccountType(GLAccount account, GLAccountType expected, String parameter) {
        if (!expected.getValue().equals(account.getType()) || account.isDisabled() || account.isHeaderAccount()) {
            throw validation(parameter, "Account must be an enabled detail " + expected.name().toLowerCase() + " account");
        }
    }

    private static <T> T required(T value, String parameter) {
        if (value == null) {
            throw validation(parameter, parameter + " is required");
        }
        return value;
    }

    private static String requiredText(String value, String parameter) {
        if (value == null || value.isBlank()) {
            throw validation(parameter, parameter + " is required");
        }
        return value;
    }

    private static BigDecimal requiredPositive(BigDecimal value, String parameter) {
        required(value, parameter);
        if (value.signum() <= 0) {
            throw validation(parameter, parameter + " must be greater than zero");
        }
        return value;
    }

    private static BigDecimal requiredNonNegative(BigDecimal value, String parameter) {
        required(value, parameter);
        if (value.signum() < 0) {
            throw validation(parameter, parameter + " must not be negative");
        }
        return value;
    }

    private static PlatformApiDataValidationException validation(String parameter, String message) {
        return new PlatformApiDataValidationException("error.msg.share.yield.invalid", message, parameter);
    }
}
