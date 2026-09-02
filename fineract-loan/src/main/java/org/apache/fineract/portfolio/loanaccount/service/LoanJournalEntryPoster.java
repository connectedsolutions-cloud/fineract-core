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

import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;

public interface LoanJournalEntryPoster {

    /**
     * Create journal entries immediately for a single loan transaction This replaces the old 2-step process of
     * collecting transaction IDs and then creating journal entries
     *
     * @param loanTransaction
     *            the loan transaction to create journal entries for
     * @param isAccountTransfer
     *            whether this is an account transfer transaction
     * @param isLoanToLoanTransfer
     *            whether this is a loan-to-loan transfer transaction
     */
    void postJournalEntriesForLoanTransaction(LoanTransaction loanTransaction, boolean isAccountTransfer, boolean isLoanToLoanTransfer);

    /**
     * Same as {@link #postJournalEntriesForLoanTransaction(LoanTransaction, boolean, boolean)} but journal entries are
     * linked to {@code overrideLoanTransactionIdForGL} instead of the given transaction's id (e.g. to group postings
     * under a single loan transaction). When null, behaves like the 3-arg overload.
     *
     * @param overrideLoanTransactionIdForGL
     *            when non-null, journal entries use this as loan_transaction_id
     */
    void postJournalEntriesForLoanTransaction(LoanTransaction loanTransaction, boolean isAccountTransfer, boolean isLoanToLoanTransfer,
            Long overrideLoanTransactionIdForGL);

    /**
     * Create journal entries immediately for an external owner transfer
     *
     * @param loan
     *            the loan being transferred
     * @param externalAssetOwnerTransfer
     *            the external owner transfer details
     * @param previousOwner
     *            the previous owner (can be null for initial transfers)
     */
    void postJournalEntriesForExternalOwnerTransfer(Loan loan, Object externalAssetOwnerTransfer, Object previousOwner);
}
