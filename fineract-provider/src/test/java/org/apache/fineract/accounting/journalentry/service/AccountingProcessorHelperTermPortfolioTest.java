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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.accounting.journalentry.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;

import java.time.LocalDate;
import java.util.Optional;
import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForLoan;
import org.apache.fineract.accounting.common.AccountingConstants.AccrualAccountsForLoan;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMapping;
import org.apache.fineract.accounting.producttoaccountmapping.domain.ProductToGLAccountMappingRepository;
import org.apache.fineract.portfolio.PortfolioProductType;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.ArgumentCaptor;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AccountingProcessorHelperTermPortfolioTest {

    @Mock
    private ProductToGLAccountMappingRepository mappingRepository;
    @Mock
    private LoanRepositoryWrapper loanRepository;
    @Mock
    private JournalEntryRepository journalRepository;
    @Mock
    private GLAccountRepository glAccountRepository;
    @Mock
    private JournalEntryPersistenceService journalEntryPersistenceService;
    @InjectMocks
    private AccountingProcessorHelper helper;

    private Loan loan;
    private GLAccount shortAccount;
    private GLAccount longAccount;

    @BeforeEach
    void setUp() throws ReflectiveOperationException {
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 2, 1))));
        final var constructor = Loan.class.getDeclaredConstructor();
        constructor.setAccessible(true);
        loan = constructor.newInstance();
        loan.setExpectedDisbursementDate(LocalDate.of(2026, 1, 1));
        loan.setExpectedMaturityDate(LocalDate.of(2027, 1, 3));
        shortAccount = account(10L);
        longAccount = account(20L);
    }

    @AfterEach
    void tearDown() {
        ThreadLocalContextUtil.reset();
    }

    @Test
    void selectsAndResolvesLongTermAccountForPrincipal() {
        configureTermMappings();
        when(loanRepository.findOneWithNotFoundDetection(1L)).thenReturn(loan);
        when(glAccountRepository.findById(20L)).thenReturn(Optional.of(longAccount));

        helper.prepareLoanPortfolioAccount(1L, 2L);

        assertThat(loan.getPortfolioAccountGlId()).isEqualTo(20L);
        assertThat(helper.getLinkedGLAccountForLoan(1L, 2L, CashAccountsForLoan.LOAN_PORTFOLIO.getValue(), null))
                .isSameAs(longAccount);
    }

    @Test
    void refusesToInferAccountForLoanWithPriorJournals() {
        configureTermMappings();
        when(loanRepository.findOneWithNotFoundDetection(1L)).thenReturn(loan);
        when(journalRepository.countUnreversedEntriesForEntity(1L, PortfolioProductType.LOAN.getValue())).thenReturn(2L);

        assertThatThrownBy(() -> helper.prepareLoanPortfolioAccount(1L, 2L)).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("reviewed portfolio-account migration");
        assertThat(loan.getPortfolioAccountGlId()).isNull();
    }

    @Test
    void principalDebitAndCreditJournalPairsUseSelectedLongAccount() {
        configureTermMappings();
        final GLAccount fundAccount = account(30L);
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                CashAccountsForLoan.FUND_SOURCE.getValue())).thenReturn(mapping(fundAccount));
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.INTEREST_RECEIVABLE.getValue())).thenReturn(null);
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.LONG_TERM_INTEREST_RECEIVABLE.getValue())).thenReturn(null);
        when(loanRepository.findOneWithNotFoundDetection(1L)).thenReturn(loan);
        when(glAccountRepository.findById(20L)).thenReturn(Optional.of(longAccount));
        helper.prepareLoanPortfolioAccount(1L, 2L);

        final Office office = Office.headOffice("Test", LocalDate.of(2026, 1, 1), ExternalId.empty());
        helper.createJournalEntriesForLoan(office, "USD", CashAccountsForLoan.LOAN_PORTFOLIO.getValue(),
                CashAccountsForLoan.FUND_SOURCE.getValue(), 2L, null, 1L, "101", LocalDate.of(2026, 1, 1),
                new BigDecimal("100.00"), null);
        helper.createJournalEntriesForLoan(office, "USD", CashAccountsForLoan.FUND_SOURCE.getValue(),
                CashAccountsForLoan.LOAN_PORTFOLIO.getValue(), 2L, null, 1L, "102", LocalDate.of(2026, 2, 1),
                new BigDecimal("25.00"), null);

        final ArgumentCaptor<JournalEntry> entries = ArgumentCaptor.forClass(JournalEntry.class);
        verify(journalEntryPersistenceService, times(4)).saveAndFlush(entries.capture());
        assertThat(entries.getAllValues()).extracting(entry -> entry.getGlAccount().getId()).containsExactly(20L, 30L, 30L, 20L);
        assertThat(entries.getAllValues()).extracting(JournalEntry::getAmount)
                .containsExactly(new BigDecimal("100.00"), new BigDecimal("100.00"), new BigDecimal("25.00"), new BigDecimal("25.00"));
    }

    @Test
    void selectsAndResolvesLongTermInterestReceivableAccount() {
        configureTermMappings();
        final GLAccount shortInterest = account(40L);
        final GLAccount longInterest = account(50L);
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.INTEREST_RECEIVABLE.getValue())).thenReturn(mapping(shortInterest));
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.LONG_TERM_INTEREST_RECEIVABLE.getValue())).thenReturn(mapping(longInterest));
        when(loanRepository.findOneWithNotFoundDetection(1L)).thenReturn(loan);
        when(glAccountRepository.findById(50L)).thenReturn(Optional.of(longInterest));

        helper.prepareLoanPortfolioAccount(1L, 2L);

        assertThat(loan.getPortfolioInterestReceivableGlId()).isEqualTo(50L);
        assertThat(helper.getLinkedGLAccountForLoan(1L, 2L, AccrualAccountsForLoan.INTEREST_RECEIVABLE.getValue(), null))
                .isSameAs(longInterest);
    }

    @Test
    void accruedInterestJournalDebitsSelectedReceivableAndCreditsIncome() {
        configureTermMappings();
        final GLAccount shortInterest = account(40L);
        final GLAccount longInterest = account(50L);
        final GLAccount interestIncome = account(60L);
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.INTEREST_RECEIVABLE.getValue())).thenReturn(mapping(shortInterest));
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.LONG_TERM_INTEREST_RECEIVABLE.getValue())).thenReturn(mapping(longInterest));
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                AccrualAccountsForLoan.INTEREST_ON_LOANS.getValue())).thenReturn(mapping(interestIncome));
        when(loanRepository.findOneWithNotFoundDetection(1L)).thenReturn(loan);
        when(glAccountRepository.findById(50L)).thenReturn(Optional.of(longInterest));
        helper.prepareLoanPortfolioAccount(1L, 2L);

        final Office office = Office.headOffice("Test", LocalDate.of(2026, 1, 1), ExternalId.empty());
        helper.createJournalEntriesForLoan(office, "USD", AccrualAccountsForLoan.INTEREST_RECEIVABLE.getValue(),
                AccrualAccountsForLoan.INTEREST_ON_LOANS.getValue(), 2L, null, 1L, "103", LocalDate.of(2026, 2, 1),
                new BigDecimal("5.00"), null);

        final ArgumentCaptor<JournalEntry> entries = ArgumentCaptor.forClass(JournalEntry.class);
        verify(journalEntryPersistenceService, times(2)).saveAndFlush(entries.capture());
        assertThat(entries.getAllValues()).extracting(entry -> entry.getGlAccount().getId()).containsExactly(50L, 60L);
    }

    private void configureTermMappings() {
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                CashAccountsForLoan.LONG_TERM_LOAN_PORTFOLIO.getValue())).thenReturn(mapping(longAccount));
        when(mappingRepository.findCoreProductToFinAccountMapping(2L, PortfolioProductType.LOAN.getValue(),
                CashAccountsForLoan.LOAN_PORTFOLIO.getValue())).thenReturn(mapping(shortAccount));
    }

    private ProductToGLAccountMapping mapping(final GLAccount account) {
        return new ProductToGLAccountMapping().setGlAccount(account);
    }

    private GLAccount account(final Long id) {
        final GLAccount account = new GLAccount();
        account.setId(id);
        return account;
    }
}
