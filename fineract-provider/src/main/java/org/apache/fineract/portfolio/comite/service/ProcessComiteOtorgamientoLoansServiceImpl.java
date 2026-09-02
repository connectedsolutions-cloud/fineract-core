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
package org.apache.fineract.portfolio.comite.service;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.accounting.accountingOperations.AvailableAtCashierAccountingHelper;
import org.apache.fineract.accounting.common.AccountingConstants.AccrualAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.journalentry.data.TaxPaymentDTO;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.loanaccount.data.ChargeTaxResult;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.service.LoanAssembler;
import org.apache.fineract.portfolio.loanaccount.service.LoanChargeService;
import org.apache.fineract.portfolio.loanaccount.service.LoanJournalEntryPoster;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessComiteOtorgamientoLoansServiceImpl implements ProcessComiteOtorgamientoLoansService {

    private final LoanAssembler loanAssembler;
    private final AccountingProcessorHelper accountingProcessorHelper;
    private final LoanChargeService loanChargeService;
    private final LoanTransactionRepository loanTransactionRepository;
    private final LoanJournalEntryPoster loanJournalEntryPoster;
    private final LoanRepositoryWrapper loanRepositoryWrapper;
    private final AvailableAtCashierAccountingHelper availableAtCashierAccountingHelper;

    @Override
    @Transactional
    public ProcessComiteOtorgamientoResult process(SesionComite session, List<Long> approvedLoanIds) {
        if (approvedLoanIds == null || approvedLoanIds.isEmpty()) {
            log.info("Comite-otorgamiento processing skipped for session {}: no approved loans to process",
                    session != null ? session.getId() : null);
            return new ProcessComiteOtorgamientoResult("applied", new JsonObject().toString());
        }

        final Long sessionId = session.getId();
        log.info("Starting comite-otorgamiento processing for session {}. Loans to process: {}", sessionId, approvedLoanIds);
        log.debug("[COMTE-DEBUG] process started sessionId={} approvedLoanIds={} count={}", sessionId, approvedLoanIds,
                approvedLoanIds != null ? approvedLoanIds.size() : 0);
        final LocalDate businessDate = DateUtils.getBusinessLocalDate();
        log.debug("[COMTE-DEBUG] process businessDate={}", businessDate);
        final JsonObject output = new JsonObject();
        final JsonArray entries = new JsonArray();
        final List<Loan> processedLoans = new ArrayList<>();

        for (Long loanId : approvedLoanIds) {
            try {
                log.debug("[COMTE-DEBUG] process processing loan sessionId={} loanId={}", sessionId, loanId);
                processOneLoan(sessionId, loanId, businessDate, entries, processedLoans);
                log.debug("[COMTE-DEBUG] process loan completed sessionId={} loanId={}", sessionId, loanId);
            } catch (Exception e) {
                log.error("[COMTE-DEBUG] Error processing loan sessionId={} loanId={}", sessionId, loanId, e);
                JsonObject err = new JsonObject();
                err.addProperty("loanId", loanId);
                err.addProperty("error", e.getMessage());
                entries.add(err);
            }
        }

        output.add("entries", entries);
        return new ProcessComiteOtorgamientoResult("applied", output.toString());
    }

    private void processOneLoan(Long sessionId, Long loanId, LocalDate businessDate, JsonArray entries, List<Loan> processedLoans) {
        Loan loan = loanAssembler.assembleFrom(loanId);

        if (loan.getDisbursalMethodPaymentType() == null || !Boolean.TRUE.equals(loan.getDisbursalMethodPaymentType().getIsCashPayment())) {
            log.debug("[COMTE-DEBUG] processOneLoan skip (not cash) sessionId={} loanId={}", sessionId, loanId);
            return;
        }
        if (loan.isComitePreProcessed()) {
            log.debug("[COMTE-DEBUG] processOneLoan skip (already pre-processed) sessionId={} loanId={}", sessionId, loanId);
            return;
        }

        Office office = loan.getOffice();
        String currencyCode = loan.getCurrencyCode();
        Long loanProductId = loan.getLoanProduct().getId();
        Long paymentTypeId = loan.getDisbursalMethodPaymentType() != null ? loan.getDisbursalMethodPaymentType().getId() : null;
        BigDecimal principal = loan.getPrincipal() != null ? loan.getPrincipal().getAmount() : loan.getApprovedPrincipal();

        log.debug("[COMTE-DEBUG] processOneLoan loan sessionId={} loanId={} principal={} activeChargesCount={}", sessionId, loanId,
                principal, loan.getActiveCharges() != null ? loan.getActiveCharges().size() : 0);

        LoanTransaction comiteTxn = LoanTransaction.comiteOtorgamiento(loan, office, businessDate, ExternalId.empty());
        loanTransactionRepository.saveAndFlush(comiteTxn);
        String comiteTxnId = comiteTxn.getId().toString();

        int loanPortfolioPlaceholderId = getLoanPortfolioPlaceholderId(loan.getLoanProduct());

        accountingProcessorHelper.createDebitJournalEntryForLoan(office, currencyCode, loanPortfolioPlaceholderId, loanProductId,
                paymentTypeId, loanId, comiteTxnId, businessDate, principal, loan.getDimensions());
        addEntry(entries, loanId, "portfolio_debit", comiteTxnId, principal, "DEBIT");

        List<LoanCharge> availableAtCashierCharges = loan.getActiveCharges().stream()
                .filter(lc -> lc.getChargeTimeType().isAvailableAtCashier()).toList();
        log.debug("[COMTE-DEBUG] processOneLoan availableAtCashierCharges sessionId={} loanId={} count={} chargeIds={}", sessionId, loanId,
                availableAtCashierCharges.size(), availableAtCashierCharges.stream().map(LoanCharge::getId).toList());

        BigDecimal availableAtCashierTotal = BigDecimal.ZERO;
        List<TaxPaymentDTO> taxPaymentsForLoan = new ArrayList<>();
        for (LoanCharge charge : availableAtCashierCharges) {
            LoanTransaction applyTxn = loanChargeService.handleChargeAppliedTransaction(loan, charge, businessDate, comiteTxn);
            if (applyTxn != null) {
                loanTransactionRepository.saveAndFlush(applyTxn);
                loanJournalEntryPoster.postJournalEntriesForLoanTransaction(applyTxn, false, false, comiteTxn.getId());
                ChargeTaxResult result = loanChargeService.chargeTaxCalculator(loan, charge, businessDate);
                BigDecimal deduction = result.getChargeBaseAmount().add(result.getTaxAmount());
                availableAtCashierTotal = availableAtCashierTotal.add(deduction);
                addEntry(entries, loanId, "charge_" + charge.getId(), "charge-" + applyTxn.getId(), result.getChargeBaseAmount(), "CHARGE");
                log.debug(
                        "[COMTE-DEBUG] processOneLoan applying available-at-cashier charge sessionId={} loanId={} chargeId={} chargeBaseAmount={} taxAmount={} deduction={}",
                        sessionId, loanId, charge.getId(), result.getChargeBaseAmount(), result.getTaxAmount(), deduction);
                log.debug(
                        "[COMTE-DEBUG] processOneLoan charge applied sessionId={} loanId={} chargeId={} txnId={} availableAtCashierTotalSoFar={}",
                        sessionId, loanId, charge.getId(), applyTxn.getId(), availableAtCashierTotal);
                var taxSplit = result.getTaxSplit();
                if (taxSplit != null && !taxSplit.isEmpty()) {
                    for (var e : taxSplit.entrySet()) {
                        if (e.getValue() != null && e.getValue().compareTo(BigDecimal.ZERO) > 0 && e.getKey().getCreditAcount() != null) {
                            taxPaymentsForLoan.add(new TaxPaymentDTO(null, e.getKey().getCreditAcount().getId(), e.getValue()));
                        }
                    }
                }
            } else {
                log.debug("[COMTE-DEBUG] processOneLoan charge apply returned null sessionId={} loanId={} chargeId={}", sessionId, loanId,
                        charge.getId());
            }
        }

        BigDecimal dueAtDispTotal = loanChargeService.deriveSumTotalChargesDueAtDisbursementForNetDisbursal(loan, businessDate);
        log.debug("[COMTE-DEBUG] processOneLoan dueAtDisbursement total sessionId={} loanId={} dueAtDispTotal={}", sessionId, loanId,
                dueAtDispTotal);

        BigDecimal disbursementAmount = principal.subtract(dueAtDispTotal).subtract(availableAtCashierTotal);
        if (disbursementAmount.compareTo(BigDecimal.ZERO) < 0) {
            disbursementAmount = BigDecimal.ZERO;
        }
        log.debug(
                "[COMTE-DEBUG] processOneLoan disbursement amount sessionId={} loanId={} principal={} dueAtDispTotal={} availableAtCashierTotal={} disbursementAmount={}",
                sessionId, loanId, principal, dueAtDispTotal, availableAtCashierTotal, disbursementAmount);

        accountingProcessorHelper.createCreditJournalEntryForLoan(office, currencyCode, FinancialActivity.DISBURSEMENTS_PAYABLE.getValue(),
                loanProductId, paymentTypeId, loanId, comiteTxnId, businessDate, disbursementAmount, loan.getDimensions());
        addEntry(entries, loanId, "disbursement_payable_credit", comiteTxnId, disbursementAmount, "CREDIT");
        if (!taxPaymentsForLoan.isEmpty()) {
            BigDecimal totalTaxAmount = taxPaymentsForLoan.stream().map(TaxPaymentDTO::getAmount).filter(a -> a != null)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            LoanTransaction taxTxn = LoanTransaction.taxOnCharge(loan, office, totalTaxAmount, businessDate, ExternalId.empty());
            loanTransactionRepository.saveAndFlush(taxTxn);
            String taxTxnId = taxTxn.getId().toString();
            accountingProcessorHelper.createJournalEntriesForLoanChargeTax(office, currencyCode, loanProductId, loanId, paymentTypeId,
                    taxTxnId, businessDate, taxPaymentsForLoan, loan.getDimensions());
            addEntry(entries, loanId, "taxes", taxTxnId, totalTaxAmount, "TAXES");
        }

        loan.setNetDisbursalAmount(disbursementAmount);
        loan.setComitePreProcessed(true);
        loanRepositoryWrapper.saveAndFlush(loan);
        processedLoans.add(loan);
        log.debug("[COMTE-DEBUG] processOneLoan done sessionId={} loanId={} comitePreProcessed=true netDisbursalAmount={}", sessionId,
                loanId, disbursementAmount);
    }

    private static int getLoanPortfolioPlaceholderId(LoanProduct product) {
        if (product.isCashBasedAccountingEnabled()) {
            return CashAccountsForLoan.LOAN_PORTFOLIO.getValue();
        }
        return AccrualAccountsForLoan.LOAN_PORTFOLIO.getValue();
    }

    private static void addEntry(JsonArray entries, Long loanId, String type, String ref, BigDecimal amount, String debitCredit) {
        JsonObject e = new JsonObject();
        e.addProperty("loanId", loanId);
        e.addProperty("type", type);
        e.addProperty("transactionId", ref);
        e.addProperty("amount", amount != null ? amount.toString() : "0");
        e.addProperty("debitCredit", debitCredit);
        entries.add(e);
    }
}
