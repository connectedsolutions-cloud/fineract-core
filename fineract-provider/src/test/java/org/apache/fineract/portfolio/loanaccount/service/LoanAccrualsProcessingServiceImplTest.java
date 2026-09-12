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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Predicate;
import java.util.stream.Stream;
import org.apache.fineract.accounting.journalentry.service.JournalEntryWritePlatformService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.configuration.domain.ConfigurationDomainService;
import org.apache.fineract.infrastructure.core.domain.ActionContext;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidByRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl.CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleGenerator;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleGeneratorFactory;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.apache.fineract.portfolio.loanproduct.domain.InterestMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockedStatic;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.transaction.support.TransactionTemplate;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
public class LoanAccrualsProcessingServiceImplTest {

    private static final MonetaryCurrency CURRENCY = new MonetaryCurrency("USD", 2, 1);
    private static MockedStatic<MoneyHelper> moneyHelper;

    @BeforeAll
    static void initMoney() {
        moneyHelper = Mockito.mockStatic(MoneyHelper.class);
        moneyHelper.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        moneyHelper.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
    }

    @AfterAll
    static void closeMoney() {
        moneyHelper.close();
    }

    @InjectMocks
    private LoanAccrualsProcessingServiceImpl accrualsProcessingService;

    @Mock
    private Loan loan;

    @Mock
    private LoanStatus loanStatus;

    @Mock
    private BusinessEventNotifierService businessEventNotifierService;

    @Mock
    private LoanTransactionRepository loanTransactionRepository;

    @Mock
    private JournalEntryWritePlatformService journalEntryWritePlatformService;

    @Mock
    private ExternalIdFactory externalIdFactory;

    @Mock
    private ConfigurationDomainService configurationDomainService;

    @Mock
    private LoanRepositoryWrapper loanRepositoryWrapper;

    @Mock
    private LoanScheduleGeneratorFactory loanScheduleFactory;

    @Mock
    private ThreadPoolTaskExecutor taskExecutor;

    @Mock
    private TransactionTemplate transactionTemplate;

    @Mock
    private LoanChargeService loanChargeService;

    @Mock
    private LoanBalanceService loanBalanceService;

    @Mock
    private PostDueAccruedInterestCalculator postDueAccruedInterestCalculator;

    @Mock
    private LoanChargePaidByRepository loanChargePaidByRepository;

    @Mock
    private LoanJournalEntryPoster journalEntryPoster;

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "default", "Default", "America/El_Salvador", null));
        ThreadLocalContextUtil.setActionContext(ActionContext.DEFAULT);
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, LocalDate.of(2026, 7, 1))));
        when(loan.isClosed()).thenReturn(false);
        when(loan.getStatus()).thenReturn(loanStatus);
        when(loanStatus.isOverpaid()).thenReturn(false);
    }

    @AfterEach
    void resetContext() {
        ThreadLocalContextUtil.reset();
    }

    @ParameterizedTest
    @MethodSource("loanStatusTestCases")
    void addPeriodicAccruals_ShouldNotProceed_WhenLoanIsClosedOrOverpaid(final boolean isClosed, final boolean isOverpaid) {
        // Given
        final LocalDate tillDate = LocalDate.now(ZoneId.systemDefault());
        when(loan.isClosed()).thenReturn(isClosed);

        when(loan.getStatus()).thenReturn(loanStatus);
        when(loanStatus.isOverpaid()).thenReturn(isOverpaid);

        // When
        accrualsProcessingService.addPeriodicAccruals(tillDate, loan);

        // Then
        verify(loan, times(1)).isClosed();

        verify(loanTransactionRepository, never()).saveAndFlush(any());
        verifyNoInteractions(journalEntryWritePlatformService);
        verify(businessEventNotifierService, never()).notifyPostBusinessEvent(any());
        verify(loan, never()).addLoanTransaction(any());
    }

    @Test
    @SuppressWarnings("unchecked")
    void addPeriodicAccrualsContinuesCredesalInterestAfterFinalDueDate() {
        final LocalDate lastDueDate = LocalDate.of(2026, 6, 28);
        final LocalDate accrualDate = lastDueDate.plusDays(3);
        final Office office = org.mockito.Mockito.mock(Office.class);
        final LoanProductRelatedDetail terms = org.mockito.Mockito.mock(LoanProductRelatedDetail.class);
        final LoanScheduleGenerator scheduleGenerator = org.mockito.Mockito.mock(LoanScheduleGenerator.class);
        final LoanRepaymentScheduleInstallment installment = new LoanRepaymentScheduleInstallment(loan, 1, lastDueDate.minusMonths(1),
                lastDueDate, new BigDecimal("350.00"), new BigDecimal("12.08"), BigDecimal.ZERO, BigDecimal.ZERO, false, null,
                BigDecimal.ZERO);
        installment.setInterestAccrued(new BigDecimal("12.08"));
        final List<LoanRepaymentScheduleInstallment> installments = List.of(installment);
        final Money unmaterializedInterest = Money.of(CURRENCY, new BigDecimal("2.42"));

        when(loan.isOpen()).thenReturn(true);
        when(loan.isPeriodicAccrualAccountingEnabledOnLoanProduct()).thenReturn(true);
        when(loan.transactionProcessingStrategy())
                .thenReturn(CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.STRATEGY_CODE);
        when(loan.getLoanProductRelatedDetail()).thenReturn(terms);
        when(loan.getLastLoanRepaymentScheduleInstallment()).thenReturn(installment);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(installments);
        when(loan.getRepaymentScheduleInstallments(any(Predicate.class))).thenAnswer(invocation -> {
            final Predicate<LoanRepaymentScheduleInstallment> predicate = invocation.getArgument(0);
            return installments.stream().filter(predicate).toList();
        });
        when(loan.getLoanCharges(any(Predicate.class))).thenAnswer(invocation -> List.<LoanCharge>of());
        when(loan.fetchRepaymentScheduleInstallment(1)).thenReturn(installment);
        when(loan.getAccruedTill()).thenReturn(lastDueDate);
        when(loan.getOffice()).thenReturn(office);
        when(loan.getLoanTransactions()).thenReturn(List.of());
        when(terms.getCurrency()).thenReturn(CURRENCY);
        when(terms.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        when(terms.getInterestCalculationPeriodMethod()).thenReturn(InterestCalculationPeriodMethod.DAILY);
        when(loanScheduleFactory.create(any(), any())).thenReturn(scheduleGenerator);
        when(configurationDomainService.retrieveOrganisationStartDate()).thenReturn(lastDueDate.minusYears(1));
        when(loanChargePaidByRepository.findChargePaidByMappingsWithoutInstallmentNumber(loan)).thenReturn(List.of());
        when(postDueAccruedInterestCalculator.calculateUnmaterializedAccruableThrough(loan, CURRENCY, installments, accrualDate))
                .thenReturn(unmaterializedInterest);
        when(externalIdFactory.create()).thenReturn(ExternalId.empty());
        when(loanTransactionRepository.save(any(LoanTransaction.class))).thenAnswer(invocation -> invocation.getArgument(0));
        when(loanTransactionRepository.saveAll(any())).thenAnswer(invocation -> invocation.getArgument(0));

        accrualsProcessingService.addPeriodicAccruals(accrualDate, loan);
        accrualsProcessingService.addPeriodicAccruals(accrualDate, loan);

        final ArgumentCaptor<LoanTransaction> transaction = ArgumentCaptor.forClass(LoanTransaction.class);
        verify(loanTransactionRepository).save(transaction.capture());
        assertEquals(accrualDate, transaction.getValue().getTransactionDate());
        assertEquals(0, new BigDecimal("2.42").compareTo(transaction.getValue().getInterestPortion(CURRENCY).getAmount()));
        verify(loan).setAccruedTill(accrualDate);
    }

    @Test
    void reprocessingKeepsCredesalInterestAccruedAfterFinalDueDate() {
        final LocalDate lastDueDate = LocalDate.of(2026, 6, 28);
        final Office office = org.mockito.Mockito.mock(Office.class);
        final LoanRepaymentScheduleInstallment installment = new LoanRepaymentScheduleInstallment(loan, 1, lastDueDate.minusMonths(1),
                lastDueDate, new BigDecimal("350.00"), new BigDecimal("12.08"), BigDecimal.ZERO, BigDecimal.ZERO, false, null,
                BigDecimal.ZERO);
        final List<LoanRepaymentScheduleInstallment> installments = List.of(installment);
        final LoanTransaction contractualAccrual = LoanTransaction.accrueInterest(office, loan, Money.of(CURRENCY, new BigDecimal("12.08")),
                lastDueDate, ExternalId.empty());
        final LoanTransaction postMaturityAccrual = LoanTransaction.accrueInterest(office, loan, Money.of(CURRENCY, new BigDecimal("2.42")),
                lastDueDate.plusDays(3), ExternalId.empty());

        when(loan.isPeriodicAccrualAccountingEnabledOnLoanProduct()).thenReturn(true);
        when(loan.transactionProcessingStrategy())
                .thenReturn(CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.STRATEGY_CODE);
        when(loan.getCurrency()).thenReturn(CURRENCY);
        when(loan.getLastLoanRepaymentScheduleInstallment()).thenReturn(installment);
        when(loan.getRepaymentScheduleInstallments()).thenReturn(installments);
        when(loanChargePaidByRepository.findChargePaidByMappingsWithoutInstallmentNumber(loan)).thenReturn(List.of());
        when(loanTransactionRepository.findNonReversedByLoanAndTypes(any(), any()))
                .thenReturn(List.of(contractualAccrual, postMaturityAccrual));

        accrualsProcessingService.reprocessExistingAccruals(loan, false);

        assertEquals(0, new BigDecimal("14.50").compareTo(installment.getInterestAccrued()));
        assertFalse(postMaturityAccrual.isReversed());
    }

    private static Stream<Arguments> loanStatusTestCases() {
        return Stream.of(Arguments.of(true, false), // Loan is closed
                Arguments.of(false, true) // Loan is overpaid
        );
    }
}
