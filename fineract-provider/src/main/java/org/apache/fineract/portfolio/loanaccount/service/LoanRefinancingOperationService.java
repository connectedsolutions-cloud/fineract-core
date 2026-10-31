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
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.journalentry.domain.GlVoucher;
import org.apache.fineract.accounting.journalentry.domain.GlVoucherRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.accounting.journalentry.service.GlVoucherWriteService;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.accounting.journalentry.service.RefinancingJournalAssembler;
import org.apache.fineract.accounting.journalentry.service.RefinancingJournalContext;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.teller.data.CashierTransactionDataValidator;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.portfolio.account.domain.AccountTransferRepository;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingCashMovement;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingCashMovementRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingOperation;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingOperationRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRefinancingSettlement;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.service.adjustment.LoanAdjustmentParameter;
import org.apache.fineract.portfolio.loanaccount.service.adjustment.LoanAdjustmentService;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Owns one refinance operation, its journals, cash entitlement and atomic undo prerequisites. */
@Service
@RequiredArgsConstructor
public class LoanRefinancingOperationService implements LoanRefinancingOperations {

    private final LoanRefinancingOperationRepository operations;
    private final LoanRefinancingCashMovementRepository cashMovements;
    private final LoanRepository loans;
    private final LoanTransactionRepository transactions;
    private final JournalEntryRepository journals;
    private final GLAccountRepository accounts;
    private final GlVoucherRepository vouchers;
    private final GlVoucherWriteService voucherWriter;
    private final JournalEntryPersistenceService journalPersistence;
    private final AccountingProcessorHelper helper;
    private final LoanAdjustmentService adjustments;
    private final PlatformSecurityContext security;
    private final AccountingCutoffPolicyService cutoff;
    private final CashierTransactionDataValidator cashierValidator;
    private final CashierRepository cashiers;
    private final CashierTransactionRepository cashierTransactions;
    private final AccountTransferRepository accountTransfers;
    private final SavingsAccountRepository savingsAccounts;

    public record Start(LoanRefinancingOperation operation, List<Loan> loans, Map<Long, Set<Long>> beforeTransactions) {
    }

    public void assertIndependentAdjustmentAllowed(Long transactionId) {
        if (operations.countActiveOwners(transactionId) > 0) {
            throw rule("atomic.reversal.required",
                    "This transaction belongs to an active refinancing; reverse the refinancing disbursement as one operation");
        }
    }

    public Start begin(Loan loan, boolean savings, boolean retained, LocalDate date) {
        if (!LoanRefinancingSurplusService.isEligible(loan)) {
            throw rule("unsupported.product",
                    "Refinance accounting requires a single-disbursement individual loan without down payments or savings-paid disbursement charges");
        }
        if (loan.isComitePreProcessed()) {
            throw rule("committee.already.posted",
                    "Resolve existing committee postings before originating this refinancing; principal must not be posted twice");
        }
        cutoff.assertJournalPersistenceAllowed(date);
        GLAccount payable = canonical("222099910201", 2);
        if (!Objects.equals(payable.getId(), helper
                .getLinkedGLAccountForLoanProduct(loan.getLoanProduct().getId(), FinancialActivity.DISBURSEMENTS_PAYABLE.getValue(), null)
                .getId())) {
            throw rule("payable.mapping", "Disbursements Payable must use the canonical combined account 222099910201");
        }
        Set<Long> ids = new HashSet<>(loan.getTopupLoanDetails().getLoanIdsToClose());
        ids.add(loan.getId());
        List<Loan> locked = lock(ids);
        var previous = operations.findFirstByLoanIdOrderByIdDesc(loan.getId());
        if (previous.isPresent() && !previous.get().isReversed()) {
            throw rule("already.originated", "This refinancing already has an active origination operation");
        }
        LoanRefinancingOperation op = new LoanRefinancingOperation();
        op.setLoanId(loan.getId());
        op.setOfficeId(loan.getOfficeId());
        op.setOperationDate(date);
        op.setCurrencyCode(loan.getCurrencyCode());
        op.setProceedsMode(retained ? "RETAINED" : savings ? "SAVINGS" : "CASH");
        operations.saveAndFlush(op);
        Map<Long, Set<Long>> before = new HashMap<>();
        locked.forEach(l -> before.put(l.getId(),
                l.getLoanTransactions().stream().map(LoanTransaction::getId).filter(Objects::nonNull).collect(Collectors.toSet())));
        return new Start(op, locked, before);
    }

    public void complete(Start start, Loan successor, RefinancingJournalContext context) {
        LoanRefinancingOperation op = start.operation();
        BigDecimal payout = successor.getNetDisbursalAmount();
        if (payout == null || payout.signum() < 0) {
            throw rule("negative.remainder", "Refinancing remainder cannot be negative");
        }
        Set<Long> funds = new HashSet<>();
        funds.add(helper
                .getLinkedGLAccountForLoanProduct(successor.getLoanProduct().getId(), FinancialActivity.ASSET_TRANSFER.getValue(), null)
                .getId());
        for (Loan l : start.loans()) {
            for (LoanTransaction t : l.getLoanTransactions()) {
                if (context.transactionIds().contains(t.getId())) {
                    Long paymentType = t.getPaymentDetail() == null || t.getPaymentDetail().getPaymentType() == null ? null
                            : t.getPaymentDetail().getPaymentType().getId();
                    funds.add(helper.getLinkedGLAccountForLoanProduct(l.getLoanProduct().getId(),
                            CashAccountsForLoan.FUND_SOURCE.getValue(), paymentType).getId());
                }
            }
        }
        GLAccount portfolio = helper.getLinkedGLAccountForLoan(successor.getId(), successor.getLoanProduct().getId(),
                CashAccountsForLoan.LOAN_PORTFOLIO.getValue(), null);
        List<JournalEntry> assembled = RefinancingJournalAssembler.assemble(context, successor.getId(),
                successor.getPrincipal().getAmount(), portfolio.getId(), funds, canonical("222099910201", 2),
                "CASH".equals(op.getProceedsMode()) ? payout : BigDecimal.ZERO);
        GlVoucher voucher = voucherWriter.createNative("REFINANCE_ORIGINATION", "Refinanciamiento de préstamo", "REFINANCING_OPERATION",
                op.getId().toString());
        for (JournalEntry entry : assembled) {
            entry.setVoucher(voucher);
            entry.setJournalNumberGroupKey("REFINANCE:" + op.getId());
            journalPersistence.saveAndFlush(entry);
            op.getJournalEntryIds().add(entry.getId());
        }
        op.setVoucherId(voucher.getId());
        op.setPayoutEntitlement("CASH".equals(op.getProceedsMode()) ? payout : BigDecimal.ZERO);
        for (Loan l : start.loans()) {
            for (LoanTransaction t : l.getLoanTransactions()) {
                if (t.getId() != null && !start.beforeTransactions().get(l.getId()).contains(t.getId())) {
                    op.getTransactionIds().add(t.getId());
                }
            }
        }
        // Accrual entries stay in their own journal/date. Keep exact provenance for the eventual unwind.
        for (Long transactionId : op.getTransactionIds()) {
            journals.findByLoanTransactionIdAndReversedFalseOrderByIdAsc(transactionId)
                    .forEach(j -> op.getJournalEntryIds().add(j.getId()));
        }
        operations.saveAndFlush(op);
    }

    @Override
    @Transactional(readOnly = true)
    public Map<String, Object> read(Long loanId) {
        Loan loan = access(loanId);
        var op = operations.findFirstByLoanIdOrderByIdDesc(loanId);
        if (op.isEmpty()) {
            return Map.of("available", false, "loanId", loanId, "legacy", loan.isTopup() && !loan.isNotDisbursed(), "blockers",
                    loan.isTopup() && !loan.isNotDisbursed() ? List.of("legacy.operation.requires.review") : List.of());
        }
        return view(op.get(), loan);
    }

    private Map<String, Object> view(LoanRefinancingOperation op, Loan loan) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("clientId", loan.getClientId());
        result.put("clientName", loan.getClient().getDisplayName());
        result.put("available", true);
        result.put("loanId", op.getLoanId());
        result.put("operationId", op.getId());
        result.put("operationDate", op.getOperationDate().toString());
        result.put("voucherId", op.getVoucherId());
        result.put("reversalDate", op.getReversalDate() == null ? null : op.getReversalDate().toString());
        result.put("proceedsMode", op.getProceedsMode());
        result.put("currencyCode", op.getCurrencyCode());
        result.put("payoutEntitlement", op.getPayoutEntitlement());
        result.put("deliveredAmount", op.getDeliveredAmount());
        result.put("returnedAmount", op.getReturnedAmount());
        result.put("outstandingCash", op.outstandingCash());
        result.put("undeliveredAmount", op.isReversed() ? BigDecimal.ZERO : op.undelivered());
        result.put("retainedRepaymentAmount",
                "RETAINED".equals(op.getProceedsMode())
                        ? loan.getLoanTransactions().stream().filter(t -> op.getTransactionIds().contains(t.getId()) && t.isRepayment())
                                .map(LoanTransaction::getAmount).reduce(BigDecimal.ZERO, BigDecimal::add)
                        : BigDecimal.ZERO);
        result.put("reversed", op.isReversed());
        result.put("legacy", op.isLegacy());
        List<String> blockers = blockers(op, loan);
        result.put("blockers", blockers);
        result.put("canReverse", !op.isReversed() && blockers.isEmpty());
        result.put("predecessors", loan.getTopupLoanDetails().getSettlements().stream().map(s -> {
            LoanTransaction payoff = transactions.findById(s.getRepaymentTransactionId()).orElseThrow();
            return Map.of("loanId", s.getLoanIdToClose(), "amount", Objects.requireNonNullElse(s.getSettlementAmount(), BigDecimal.ZERO),
                    "principal", Objects.requireNonNullElse(payoff.getPrincipalPortion(), BigDecimal.ZERO), "interest",
                    Objects.requireNonNullElse(payoff.getInterestPortion(), BigDecimal.ZERO), "fees",
                    Objects.requireNonNullElse(payoff.getFeeChargesPortion(), BigDecimal.ZERO), "penalties",
                    Objects.requireNonNullElse(payoff.getPenaltyChargesPortion(), BigDecimal.ZERO));
        }).toList());
        result.put("cashMovements",
                cashMovements.findByOperationIdOrderByIdAsc(op.getId()).stream()
                        .map(m -> Map.of("id", m.getId(), "type", m.getMovementType(), "amount", m.getAmount(), "date",
                                m.getMovementDate().toString(), "externalId", m.getExternalId(), "note", m.getNote(), "voucherId",
                                m.getVoucherId()))
                        .toList());
        return result;
    }

    @Override
    @Transactional(readOnly = true)
    public List<Map<String, Object>> pending(Long officeId) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (LoanRefinancingOperation op : operations.findPendingCash()) {
            Loan loan = loans.findById(op.getLoanId()).orElseThrow();
            if ((officeId == null || officeId.equals(op.getOfficeId())) && visible(loan)) {
                result.add(view(op, loan));
            }
        }
        return result;
    }

    @Override
    @Transactional
    public CommandProcessingResult cashMovement(Long loanId, JsonCommand command, boolean returned) {
        security.authenticatedUser().validateHasPermissionTo(returned ? "RETURNREFINANCE_LOAN" : "PAYOUTREFINANCE_LOAN");
        Loan loan = access(loanId);
        lock(Set.of(loanId));
        LoanRefinancingOperation op = operations.findFirstByLoanIdOrderByIdDesc(loanId)
                .orElseThrow(() -> rule("missing.operation", "No tracked refinancing operation exists"));
        String externalId = command.stringValueOfParameterNamed("externalId");
        BigDecimal amount = command.bigDecimalValueOfParameterNamed("transactionAmount");
        LocalDate date = command.localDateValueOfParameterNamed("transactionDate");
        String note = command.stringValueOfParameterNamed("note");
        if (externalId == null || externalId.isBlank() || externalId.length() > 100 || amount == null || amount.signum() <= 0
                || amount.stripTrailingZeros().scale() > loan.getCurrency().getDigitsAfterDecimal() || date == null || note == null
                || note.isBlank() || note.length() > 1000) {
            throw rule("invalid.cash.movement", "A positive currency-precision amount, date, reason and unique externalId are required");
        }
        String kind = returned ? "RETURN" : "PAYOUT";
        var duplicate = cashMovements.findByExternalId(externalId);
        if (duplicate.isPresent()) {
            var existing = duplicate.get();
            if (!existing.getOperationId().equals(op.getId()) || !kind.equals(existing.getMovementType())
                    || existing.getAmount().compareTo(amount) != 0 || !date.equals(existing.getMovementDate())
                    || !Objects.equals(note, existing.getNote())) {
                throw rule("external.id.conflict", "The externalId belongs to a different cash movement");
            }
            return cashResult(command, loan, existing);
        }
        if (op.isReversed() || !"CASH".equals(op.getProceedsMode())) {
            throw rule("cash.not.available", "This operation has no cash payout or return to process");
        }
        if (date.isBefore(op.getOperationDate()) || date.isAfter(DateUtils.getBusinessLocalDate())) {
            throw rule("invalid.cash.date", "Cash movement must be between origination and the business date");
        }
        BigDecimal available = returned ? op.outstandingCash() : op.undelivered();
        if (amount.compareTo(available) > 0) {
            throw rule("cash.amount.exceeds.available", "Requested cash amount exceeds the outstanding amount");
        }
        if (!returned && op.getReturnedAmount().signum() > 0) {
            throw rule("cash.return.in.progress", "Cash has been returned for reversal; further payout is blocked");
        }
        cutoff.assertJournalPersistenceAllowed(date);
        helper.checkForBranchClosures(helper.getLatestClosureByBranch(loan.getOfficeId()), date);
        GLAccount cash = canonical("1110010199", 1);
        if (!Objects.equals(cash.getId(),
                helper.getLinkedGLAccountForLoanProduct(loan.getLoanProduct().getId(), FinancialActivity.CASH_AT_TELLER.getValue(), null)
                        .getId())) {
            throw rule("teller.mapping", "Cash at Teller must use the canonical combined account 1110010199");
        }
        Cashier cashier = activeCashier(loan, date);
        if (!returned) {
            cashierValidator.validateSettleCashAndCashOutTransactions(cashier.getId(), loan.getCurrencyCode(), amount);
        }
        LoanRefinancingCashMovement movement = new LoanRefinancingCashMovement();
        movement.setOperationId(op.getId());
        movement.setExternalId(externalId);
        movement.setMovementType(kind);
        movement.setAmount(amount);
        movement.setMovementDate(date);
        movement.setCreatedBy(security.authenticatedUser().getId());
        movement.setNote(note);
        cashMovements.saveAndFlush(movement);
        GlVoucher voucher = voucherWriter.createNative(returned ? "REFINANCE_CASH_RETURN" : "REFINANCE_PAYOUT",
                returned ? "Devolución de desembolso de refinanciamiento" : "Entrega de desembolso de refinanciamiento",
                "REFINANCING_CASH_MOVEMENT", movement.getId().toString());
        GLAccount payable = canonical("222099910201", 2);
        String transactionId = "REFICASH" + movement.getId();
        saveCashEntry(loan, voucher, transactionId, date, amount, returned ? cash : payable, JournalEntryType.DEBIT);
        saveCashEntry(loan, voucher, transactionId, date, amount, returned ? payable : cash, JournalEntryType.CREDIT);
        CashierTransaction cashEvent = CashierTransaction.createBalanceTransaction(cashier, returned ? 103 : 104, amount, date,
                loan.getCurrencyCode(), "Refinancing " + kind + " #" + movement.getId() + ": " + note).setEntityType("loans")
                .setEntityId(loan.getId());
        cashierTransactions.saveAndFlush(cashEvent);
        movement.setCashierTransactionId(cashEvent.getId());
        movement.setVoucherId(voucher.getId());
        cashMovements.saveAndFlush(movement);
        if (returned) {
            op.setReturnedAmount(op.getReturnedAmount().add(amount));
        } else {
            op.setDeliveredAmount(op.getDeliveredAmount().add(amount));
        }
        operations.saveAndFlush(op);
        return cashResult(command, loan, movement);
    }

    private Cashier activeCashier(Loan loan, LocalDate date) {
        var staff = security.authenticatedUser().getStaff();
        if (staff == null || !date.equals(DateUtils.getBusinessLocalDate())) {
            throw rule("cashier.required",
                    "Actual cash movements require the current business date and an active cashier assigned to the operator");
        }
        LocalTime time = DateUtils.getOffsetDateTimeOfTenant().toLocalTime();
        List<Cashier> active = cashiers.findByStaffIdForRefinancingUpdate(staff.getId()).stream()
                .filter(c -> c.getTeller().getOffice().getId().equals(loan.getOfficeId()) && c.getTeller().getStatus() == 300
                        && !date.isBefore(c.getStartDate()) && (c.getEndDate() == null || !date.isAfter(c.getEndDate()))
                        && c.getClosingBalance() == null
                        && (c.getTeller().getStartDate() == null || !date.isBefore(c.getTeller().getStartDate()))
                        && (c.getTeller().getEndDate() == null || !date.isAfter(c.getTeller().getEndDate()))
                        && (Boolean.TRUE.equals(c.getIsFullDay())
                                || (c.getStartTime() != null && !time.isBefore(LocalTime.parse(c.getStartTime()))
                                        && (c.getEndTime() == null || !time.isAfter(LocalTime.parse(c.getEndTime()))))))
                .toList();
        if (active.size() != 1) {
            throw rule("cashier.required", "Exactly one open cashier session in the loan office is required");
        }
        return active.getFirst();
    }

    private void saveCashEntry(Loan loan, GlVoucher voucher, String transactionId, LocalDate date, BigDecimal amount, GLAccount account,
            JournalEntryType type) {
        JournalEntry entry = JournalEntry.createNew(loan.getOffice(), null, account, loan.getCurrencyCode(), transactionId, false, date,
                type, amount, "Refinance cash movement", 1, loan.getId(), null, null, null, null, null, loan.getDimensions());
        entry.setVoucher(voucher);
        journalPersistence.saveAndFlush(entry);
    }

    private CommandProcessingResult cashResult(JsonCommand command, Loan loan, LoanRefinancingCashMovement movement) {
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(loan.getId()).withLoanId(loan.getId())
                .withOfficeId(loan.getOfficeId()).withClientId(loan.getClientId()).withSubEntityId(movement.getId())
                .with(Map.of("refinancingCashMovementId", movement.getId(), "amount", movement.getAmount(), "type",
                        movement.getMovementType()))
                .build();
    }

    public LoanRefinancingOperation prepareUndo(Loan successor, LocalDate date) {
        Set<Long> ids = new HashSet<>(successor.getTopupLoanDetails().getLoanIdsToClose());
        ids.add(successor.getId());
        lock(ids);
        LoanRefinancingOperation op = operations.findFirstByLoanIdOrderByIdDesc(successor.getId())
                .orElseThrow(() -> rule("legacy.operation.requires.review",
                        "This legacy refinancing needs reviewed operation provenance before reversal"));
        if (op.isReversed()) {
            return op;
        }
        if ("SAVINGS".equals(op.getProceedsMode())) {
            List<Long> savingsIds = accountTransfers.findAllByLoanId(successor.getId()).stream()
                    .filter(t -> t.getFromLoanTransaction() != null && op.getTransactionIds().contains(t.getFromLoanTransaction().getId())
                            && t.getToSavingsTransaction() != null)
                    .map(t -> t.getToSavingsTransaction().getSavingsAccount().getId()).distinct().sorted().toList();
            savingsIds.forEach(savingsAccounts::findOneLocked);
        }
        cutoff.assertJournalPersistenceAllowed(date);
        for (Long id : ids) {
            helper.checkForBranchClosures(helper.getLatestClosureByBranch(loans.findById(id).orElseThrow().getOfficeId()), date);
        }
        if (date.isBefore(op.getOperationDate()) || !date.equals(DateUtils.getBusinessLocalDate())) {
            throw rule("invalid.reversal.date", "Refinance reversals must use the current business date");
        }
        List<String> blockers = blockers(op, successor);
        if (!blockers.isEmpty()) {
            throw rule("reversal.blocked", "Resolve refinancing reversal blockers: " + String.join(", ", blockers));
        }
        return op;
    }

    public Set<Long> operationLoanIds(Loan successor) {
        Set<Long> ids = new HashSet<>(successor.getTopupLoanDetails().getLoanIdsToClose());
        ids.add(successor.getId());
        return ids;
    }

    public void reversePredecessors(Loan successor, LoanRefinancingOperation op, JsonCommand command, LocalDate date) {
        for (LoanRefinancingSettlement settlement : successor.getTopupLoanDetails().getSettlements()) {
            LoanTransaction payoff = transactions.findById(settlement.getRepaymentTransactionId()).orElseThrow();
            if (!op.getTransactionIds().contains(payoff.getId()) || payoff.isReversed()) {
                throw rule("settlement.changed", "A predecessor settlement changed after origination");
            }
            Loan old = payoff.getLoan();
            LoanAdjustmentParameter parameter = LoanAdjustmentParameter.builder().transactionAmount(BigDecimal.ZERO)
                    .transactionDate(payoff.getTransactionDate()).reversalEffectiveDate(date).txnExternalId(ExternalId.empty())
                    .reversalTxnExternalId(ExternalId.empty()).noteText(command.stringValueOfParameterNamed("note")).build();
            adjustments.adjustLoanTransaction(old, payoff, parameter, command.commandId(), new HashMap<>());
        }
    }

    public void finishUndo(LoanRefinancingOperation op, LocalDate date) {
        GlVoucher original = vouchers.findById(op.getVoucherId()).orElseThrow();
        GlVoucher reversal = voucherWriter.createReversal(original, "4", "Reversión de refinanciamiento", "REFINANCE_REVERSAL");
        List<JournalEntry> originals = journals.findAllById(op.getJournalEntryIds());
        for (JournalEntry entry : originals) {
            if (entry.isReversed()) {
                throw rule("journal.changed", "A refinancing journal was independently reversed");
            }
            JournalEntry contra = JournalEntry.createNew(entry.getOffice(), entry.getPaymentDetail(), entry.getGlAccount(),
                    entry.getCurrencyCode(), "REFIUNDO" + op.getId(), false, date,
                    entry.isDebitEntry() ? JournalEntryType.CREDIT : JournalEntryType.DEBIT, entry.getAmount(), "Refinance reversal",
                    entry.getEntityType(), entry.getEntityId(), null, entry.getLoanTransactionId(), entry.getSavingsTransactionId(),
                    entry.getClientTransactionId(), entry.getShareTransactionId(), entry.getDimensions());
            contra.setVoucher(reversal);
            contra.setJournalNumberGroupKey("REFIUNDO:" + op.getId());
            journalPersistence.saveAndFlush(contra);
            entry.setReversed(true);
            entry.setReversalJournalEntry(contra);
            journalPersistence.saveAndFlush(entry);
        }
        op.setReversed(true);
        op.setReversalDate(date);
        operations.saveAndFlush(op);
    }

    private List<String> blockers(LoanRefinancingOperation op, Loan successor) {
        List<String> result = new ArrayList<>();
        if (op.isReversed()) {
            return result;
        }
        if (op.outstandingCash().signum() > 0) {
            result.add("cash.return.required");
        }
        var ownedJournals = journals.findAllById(op.getJournalEntryIds());
        if (ownedJournals.size() != op.getJournalEntryIds().size() || ownedJournals.stream().anyMatch(JournalEntry::isReversed)) {
            result.add("accounting.entries.changed");
        }
        for (Long id : operationLoanIds(successor)) {
            Loan loan = loans.findById(id).orElseThrow();
            long lastOwned = loan.getLoanTransactions().stream().filter(t -> op.getTransactionIds().contains(t.getId()))
                    .mapToLong(LoanTransaction::getId).max().orElse(0);
            if (loan.getLoanTransactions().stream()
                    .anyMatch(t -> loan.isUserTransaction(t) && !op.getTransactionIds().contains(t.getId()) && t.getId() > lastOwned)) {
                result.add("later.activity.loan." + id);
            }
        }
        if ("SAVINGS".equals(op.getProceedsMode())) {
            for (var transfer : accountTransfers.findAllByLoanId(successor.getId())) {
                var deposit = transfer.getToSavingsTransaction();
                if (deposit != null && transfer.getFromLoanTransaction() != null
                        && op.getTransactionIds().contains(transfer.getFromLoanTransaction().getId())) {
                    if (deposit.isReversed() || deposit.getSavingsAccount().getTransactions().stream()
                            .anyMatch(t -> !t.isReversed() && t.getId() > deposit.getId() && t.getAmount().signum() > 0)) {
                        result.add("later.activity.savings." + deposit.getSavingsAccount().getId());
                    }
                }
            }
        }
        return result;
    }

    private Loan access(Long loanId) {
        Loan loan = loans.findById(loanId).orElseThrow();
        if (!visible(loan)) {
            throw rule("office.access.denied", "Loan is outside the current user's office scope");
        }
        return loan;
    }

    private boolean visible(Loan loan) {
        return loan.getOffice().getHierarchy().startsWith(security.authenticatedUser().getOffice().getHierarchy());
    }

    private List<Loan> lock(Set<Long> ids) {
        List<Loan> result = loans.findAllByIdForRefinancingUpdate(ids.stream().sorted().toList());
        if (result.size() != ids.size()) {
            throw rule("loan.missing", "A related loan no longer exists");
        }
        result.forEach(l -> {
            if (!visible(l)) {
                throw rule("office.access.denied", "A related loan is outside the operator's office scope");
            }
        });
        return result;
    }

    private GLAccount canonical(String code, int type) {
        GLAccount account = accounts.findOneByGlCode(code)
                .orElseThrow(() -> rule("account.missing", "Required GL account is missing: " + code));
        if (account.isDisabled() || !account.isDetailAccount() || account.getType() != type) {
            throw rule("account.invalid", "Required active posting account is invalid: " + code);
        }
        return account;
    }

    private static GeneralPlatformDomainRuleException rule(String suffix, String message) {
        return new GeneralPlatformDomainRuleException("error.msg.loan.refinancing." + suffix, message);
    }
}
