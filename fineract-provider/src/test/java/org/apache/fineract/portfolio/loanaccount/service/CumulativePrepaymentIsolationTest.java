/*
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements.
 * See the NOTICE file distributed with this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License. You may obtain a copy of the License at
 * http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software distributed under the License is
 * distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.service;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.persistence.EntityManager;
import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.FineractPlatformTenant;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.ExternalIdFactory;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.MoneyHelper;
import org.apache.fineract.organisation.monetary.mapper.CurrencyMapper;
import org.apache.fineract.portfolio.loanaccount.data.HolidayDetailDTO;
import org.apache.fineract.portfolio.loanaccount.data.OutstandingAmountsDTO;
import org.apache.fineract.portfolio.loanaccount.data.ScheduleGeneratorDTO;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidBy;
import org.apache.fineract.portfolio.loanaccount.domain.LoanInstallmentCharge;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleTransactionProcessorFactory;
import org.apache.fineract.portfolio.loanaccount.domain.LoanStatus;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionToRepaymentScheduleMapping;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionType;
import org.apache.fineract.portfolio.loanaccount.domain.SourceExactRepaymentAllocation;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.LoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.PostDueAccruedInterestCalculator;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl.CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.loanschedule.data.LoanScheduleDTO;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.CumulativeDecliningBalanceInterestLoanScheduleGenerator;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanApplicationTerms;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleGeneratorFactory;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleType;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.PaymentPeriodsInOneYearCalculator;
import org.apache.fineract.portfolio.loanaccount.loanschedule.domain.ScheduledDateGenerator;
import org.apache.fineract.portfolio.loanaccount.mapper.LoanTermVariationsMapper;
import org.apache.fineract.portfolio.loanaccount.serialization.LoanChargeValidator;
import org.apache.fineract.portfolio.loanproduct.domain.InterestMethod;
import org.apache.fineract.portfolio.loanproduct.domain.LoanPreCloseInterestCalculationStrategy;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRelatedDetail;
import org.eclipse.persistence.descriptors.RelationalDescriptor;
import org.eclipse.persistence.descriptors.changetracking.DeferredChangeDetectionPolicy;
import org.eclipse.persistence.jpa.JpaEntityManager;
import org.eclipse.persistence.logging.SessionLog;
import org.eclipse.persistence.mappings.DirectToFieldMapping;
import org.eclipse.persistence.mappings.OneToManyMapping;
import org.eclipse.persistence.mappings.OneToOneMapping;
import org.eclipse.persistence.mappings.converters.EnumTypeConverter;
import org.eclipse.persistence.platform.database.H2Platform;
import org.eclipse.persistence.sessions.DatabaseLogin;
import org.eclipse.persistence.sessions.DatabaseRecord;
import org.eclipse.persistence.sessions.DatabaseSession;
import org.eclipse.persistence.sessions.Project;
import org.eclipse.persistence.sessions.UnitOfWork;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.MockedStatic;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.util.ReflectionUtils;

/**
 * Actual domain processor + EclipseLink flush, with a minimal synthetic persistence model and an isolated H2 database.
 */
class CumulativePrepaymentIsolationTest {

    private static final MonetaryCurrency USD = new MonetaryCurrency("USD", 2, 1);
    private static final LocalDate DAY = LocalDate.of(2026, 6, 15);
    private DatabaseSession session;
    private UnitOfWork work;
    private MockedStatic<MoneyHelper> money;
    private Loan loan;
    private LoanTransaction repayment;
    private LoanRepaymentScheduleInstallment persistedInstallment;
    private LoanCharge charge;
    private boolean rejectPreview;
    private LoanTransactionRepository repository;
    private CumulativeDecliningBalanceInterestLoanScheduleGenerator generator;
    private LoanApplicationTerms terms;
    private LoanTransactionProcessingServiceImpl service;

    @BeforeEach
    void setUp() throws Exception {
        money = mockStatic(MoneyHelper.class);
        money.when(MoneyHelper::getMathContext).thenReturn(new MathContext(19, RoundingMode.HALF_EVEN));
        money.when(MoneyHelper::getRoundingMode).thenReturn(RoundingMode.HALF_EVEN);
        ThreadLocalContextUtil.setTenant(new FineractPlatformTenant(1L, "ls07-test", "Synthetic", "America/El_Salvador", null));
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, DAY)));
        session = persistenceSession();
        work = session.acquireUnitOfWork();
        // Repository objects are managed by this real EclipseLink unit of work.
        loan = (Loan) work.readObject(Loan.class);
        repayment = loan.getLoanTransactions().getFirst();
        persistedInstallment = loan.getRepaymentScheduleInstallments().getFirst();
        final LoanProductRelatedDetail detail = mock(LoanProductRelatedDetail.class);
        when(detail.getCurrency()).thenReturn(USD);
        when(detail.getAnnualNominalInterestRate()).thenReturn(BigDecimal.ONE);
        when(detail.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        when(detail.getLoanScheduleType()).thenReturn(LoanScheduleType.CUMULATIVE);
        ReflectionTestUtils.setField(loan, "loanRepaymentScheduleDetail", detail);
        ReflectionTestUtils.setField(loan, "loanStatus", LoanStatus.ACTIVE);
        ReflectionTestUtils.setField(loan, "transactionProcessingStrategyCode", "credesal-accrued-interest-first-strategy");
        repayment.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(new BigDecimal("10"), new BigDecimal("2"), BigDecimal.ZERO, BigDecimal.ZERO));
        // Freeze the synthetic fixture before taking the preview baseline.
        work.commit();
        work = session.acquireUnitOfWork();
        loan = (Loan) work.readObject(Loan.class);
        repayment = loan.getLoanTransactions().getFirst();
        persistedInstallment = loan.getRepaymentScheduleInstallments().getFirst();
        ReflectionTestUtils.setField(loan, "loanRepaymentScheduleDetail", detail);
        ReflectionTestUtils.setField(loan, "loanStatus", LoanStatus.ACTIVE);
        ReflectionTestUtils.setField(loan, "transactionProcessingStrategyCode", "credesal-accrued-interest-first-strategy");
        charge = loan.getActiveCharges().iterator().next();
        repository = mock(LoanTransactionRepository.class);
        when(repository.findNonReversedTransactionsForReprocessingByLoan(any())).thenReturn(List.of(repayment));
        generator = spy(new CumulativeDecliningBalanceInterestLoanScheduleGenerator(mock(ScheduledDateGenerator.class),
                mock(PaymentPeriodsInOneYearCalculator.class), repository, mock(CurrencyMapper.class)));
        // Keep schedule mathematics out of this persistence regression. Its real calculator and processor still
        // execute.
        doAnswer(invocation -> {
            final Loan calculationLoan = invocation.getArgument(2);
            if (calculationLoan != loan) {
                final var copiedCharge = calculationLoan.getActiveCharges().iterator().next();
                final var copiedOwner = copiedCharge.getLoanChargePaidBySet().iterator().next();
                assertNotSame(charge, copiedCharge);
                assertSame(calculationLoan.getLoanTransactions().getFirst(), copiedOwner.getLoanTransaction());
                assertSame(copiedCharge, copiedOwner.getLoanCharge());
            }
            // Also exercise mutation of a retained installment before final replay.
            calculationLoan.getRepaymentScheduleInstallments().getFirst().resetDerivedComponents();
            calculationLoan.getActiveCharges().forEach(c -> c.resetPaidAmount(USD));
            if (rejectPreview) throw new IllegalStateException("synthetic schedule refusal");
            final LoanRepaymentScheduleInstallment temporary = new LoanRepaymentScheduleInstallment(null, 1, DAY.minusDays(15),
                    DAY.plusDays(15), new BigDecimal("100"), new BigDecimal("10"), BigDecimal.ZERO, BigDecimal.ZERO, false, null);
            temporary.setId(900L);
            return LoanScheduleDTO.from(new ArrayList<>(List.of(temporary)), null);
        }).when(generator).rescheduleNextInstallments(any(), any(), any(), any(), any(), any(), any());
        final EntityManager manager = mock(EntityManager.class);
        final JpaEntityManager eclipse = mock(JpaEntityManager.class);
        when(manager.unwrap(JpaEntityManager.class)).thenReturn(eclipse);
        when(eclipse.getActiveSession()).thenReturn(work);
        ReflectionTestUtils.setField(generator, "entityManager", manager);
        terms = mock(LoanApplicationTerms.class);
        when(terms.getExpectedDisbursementDate()).thenReturn(DAY.minusDays(15));
        when(terms.getPreClosureInterestCalculationStrategy()).thenReturn(LoanPreCloseInterestCalculationStrategy.TILL_PRE_CLOSURE_DATE);
        when(terms.getLoanScheduleType()).thenReturn(LoanScheduleType.CUMULATIVE);
        when(terms.getInterestMethod()).thenReturn(InterestMethod.DECLINING_BALANCE);
        final var factory = mock(LoanRepaymentScheduleTransactionProcessorFactory.class);
        final var processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), mock(PostDueAccruedInterestCalculator.class));
        when(factory.determineProcessor(any())).thenReturn(processor);
        final var mapper = mock(LoanTermVariationsMapper.class);
        when(mapper.constructLoanApplicationTerms(any(), any())).thenReturn(terms);
        service = new LoanTransactionProcessingServiceImpl(factory, mapper, mock(InterestScheduleModelRepositoryWrapper.class),
                mock(LoanTransactionService.class), mock(PostDueAccruedInterestCalculator.class));
    }

    @AfterEach
    void tearDown() {
        if (work != null && work.isActive()) work.release();
        if (session != null && session.isConnected()) session.logout();
        ThreadLocalContextUtil.reset();
        if (money != null) money.close();
    }

    @ParameterizedTest(name = "preview preserves persistent state with recalculation={0}")
    @ValueSource(booleans = {false, true})
    void previewAndSubsequentFlushPreservePersistentState(boolean recalculation) {
        when(loan.getLoanProductRelatedDetail().isInterestRecalculationEnabled()).thenReturn(recalculation);
        final ScheduleGeneratorDTO dto = mock(ScheduleGeneratorDTO.class);
        final LoanScheduleGeneratorFactory scheduleFactory = mock(LoanScheduleGeneratorFactory.class);
        when(dto.getLoanScheduleFactory()).thenReturn(scheduleFactory);
        when(scheduleFactory.create(any(), any())).thenReturn(generator);
        final var originalMapping = repayment.getLoanTransactionToRepaymentScheduleMappings().iterator().next();
        final var originalPrincipalPaid = persistedInstallment.getPrincipalCompleted();
        final var originalInterestPaid = persistedInstallment.getInterestPaid();
        for (int repeat = 0; repeat < 2; repeat++) {
            final OutstandingAmountsDTO quote = service.fetchPrepaymentDetail(dto, DAY, loan);
            assertEquals(new BigDecimal("90.00"), quote.principal().getAmount());
            assertEquals(new BigDecimal("8.00"), quote.interest().getAmount());
        }
        // Equivalent to the auto-flush before the payment-type query, but against an isolated database.
        assertDoesNotThrow(() -> work.writeChanges());
        assertSame(originalMapping, repayment.getLoanTransactionToRepaymentScheduleMappings().iterator().next());
        assertSame(persistedInstallment, originalMapping.getLoanRepaymentScheduleInstallment());
        assertEquals(originalPrincipalPaid, persistedInstallment.getPrincipalCompleted());
        assertEquals(originalInterestPaid, persistedInstallment.getInterestPaid());
        assertEquals(new BigDecimal("3.00"), charge.getAmountPaid());
        assertEquals(new BigDecimal("7.00"), charge.getAmountOutstanding());
        if (!recalculation) verify(repository, never()).findNonReversedTransactionsForReprocessingByLoan(any());
    }

    @Test
    void rejectedPreviewLeavesOriginalChargeAndInstallmentUnchanged() {
        rejectPreview = true;
        assertThrows(IllegalStateException.class, () -> generator.calculatePrepaymentAmount(USD, DAY, terms, MoneyHelper.getMathContext(),
                loan, mock(HolidayDetailDTO.class), mock(LoanRepaymentScheduleTransactionProcessor.class)));
        assertEquals(new BigDecimal("3.00"), charge.getAmountPaid());
        assertEquals(new BigDecimal("10.00"), persistedInstallment.getPrincipalCompleted());
        assertFalse(work.hasChanges());
        assertDoesNotThrow(() -> work.writeChanges());
    }

    @Test
    void previewPreservesPendingCallerPaymentStateInsteadOfClearingOrRestoringIt() {
        charge.setAmountPaid(new BigDecimal("4.00"));
        charge.setAmountOutstanding(new BigDecimal("6.00"));
        final var processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), mock(PostDueAccruedInterestCalculator.class));
        generator.calculatePrepaymentAmount(USD, DAY, terms, MoneyHelper.getMathContext(), loan, mock(HolidayDetailDTO.class), processor);
        assertEquals(new BigDecimal("4.00"), charge.getAmountPaid());
        assertEquals(new BigDecimal("6.00"), charge.getAmountOutstanding());
        assertTrue(work.hasChanges());
        assertDoesNotThrow(() -> work.commit());
        final var row = (DatabaseRecord) session.executeSQL("SELECT AMOUNTPAID FROM LS07_CHARGE WHERE ID=41").getFirst();
        assertEquals(new BigDecimal("4.00"), row.get("AMOUNTPAID"));
    }

    @Test
    void finalSourceExactAllocationRemainsStrictAndRejectionDoesNotLeakIntoManagedState() {
        repayment.markAsSourceExactAllocation(
                new SourceExactRepaymentAllocation(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, new BigDecimal("12")));
        final var mapping = repayment.getLoanTransactionToRepaymentScheduleMappings().iterator().next();
        final var processor = new CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor(mock(ExternalIdFactory.class),
                mock(LoanChargeValidator.class), mock(LoanBalanceService.class), mock(PostDueAccruedInterestCalculator.class));
        assertThrows(GeneralPlatformDomainRuleException.class, () -> generator.calculatePrepaymentAmount(USD, DAY, terms,
                MoneyHelper.getMathContext(), loan, mock(HolidayDetailDTO.class), processor));
        assertSame(mapping, repayment.getLoanTransactionToRepaymentScheduleMappings().iterator().next());
        assertEquals(new BigDecimal("3.00"), charge.getAmountPaid());
        assertEquals(new BigDecimal("10.00"), persistedInstallment.getPrincipalCompleted());
        assertDoesNotThrow(() -> work.writeChanges());
    }

    private static DatabaseSession persistenceSession() {
        final Project project = new Project();
        final var loan = descriptor(Loan.class, "LS07_LOAN", "id");
        owned(loan, "loanTransactions", LoanTransaction.class, "LS07_TX.LOAN_ID");
        owned(loan, "repaymentScheduleInstallments", LoanRepaymentScheduleInstallment.class, "LS07_INSTALLMENT.LOAN_ID");
        owned(loan, "charges", LoanCharge.class, "LS07_CHARGE.LOAN_ID");
        final var charge = descriptor(LoanCharge.class, "LS07_CHARGE", "id", "amount", "amountPaid", "amountWaived", "amountWrittenOff",
                "amountOutstanding", "active", "chargeTime", "chargeCalculation");
        charge.addDirectMapping("dueDate", "DUE_DATE");
        owned(charge, "loanInstallmentCharge", LoanInstallmentCharge.class, "LS07_INSTALLMENT_CHARGE.CHARGE_ID");
        owned(charge, "loanChargePaidBySet", LoanChargePaidBy.class, "LS07_CHARGE_PAID_BY.CHARGE_ID");
        final var chargePaidBy = descriptor(LoanChargePaidBy.class, "LS07_CHARGE_PAID_BY", "id", "amount");
        reference(chargePaidBy, "loanCharge", LoanCharge.class, "CHARGE_ID", "LS07_CHARGE.ID", false);
        reference(chargePaidBy, "loanTransaction", LoanTransaction.class, "TX_ID", "LS07_TX.ID", false);
        final var installmentCharge = descriptor(LoanInstallmentCharge.class, "LS07_INSTALLMENT_CHARGE", "id");
        reference(installmentCharge, "loancharge", LoanCharge.class, "CHARGE_ID", "LS07_CHARGE.ID", false);
        reference(charge, "loan", Loan.class, "LOAN_ID", "LS07_LOAN.ID", false);
        final var tx = descriptor(LoanTransaction.class, "LS07_TX", "id", "amount", "principalPortion", "interestPortion",
                "feeChargesPortion", "penaltyChargesPortion", "sourceExactAllocation", "sourceExactPrincipalPortion",
                "sourceExactInterestPortion", "sourceExactFeeChargesPortion", "sourceExactPenaltyChargesPortion");
        // Use direct converters for the two nonnumeric persisted transaction values.
        final var type = (DirectToFieldMapping) tx.addDirectMapping("typeOf", "KIND");
        type.setConverter(new EnumTypeConverter(type, LoanTransactionType.class, false));
        tx.addDirectMapping("dateOf", "TX_DATE");
        reference(tx, "loan", Loan.class, "LOAN_ID", "LS07_LOAN.ID", false);
        owned(tx, "loanTransactionToRepaymentScheduleMappings", LoanTransactionToRepaymentScheduleMapping.class, "LS07_MAPPING.TX_ID");
        final var installment = descriptor(LoanRepaymentScheduleInstallment.class, "LS07_INSTALLMENT", "id", "principal", "interestCharged",
                "principalCompleted", "interestPaid");
        installment.addDirectMapping("installmentNumber", "INSTALLMENT_NUMBER");
        installment.addDirectMapping("fromDate", "FROM_DATE");
        installment.addDirectMapping("dueDate", "DUE_DATE");
        reference(installment, "loan", Loan.class, "LOAN_ID", "LS07_LOAN.ID", false);
        final var mapping = descriptor(LoanTransactionToRepaymentScheduleMapping.class, "LS07_MAPPING", "id", "principalPortion",
                "interestPortion", "feeChargesPortion", "penaltyChargesPortion", "amount");
        reference(mapping, "loanTransaction", LoanTransaction.class, "TX_ID", "LS07_TX.ID", false);
        reference(mapping, "installment", LoanRepaymentScheduleInstallment.class, "INSTALLMENT_ID", "LS07_INSTALLMENT.ID", true);
        project.addDescriptor(loan);
        project.addDescriptor(charge);
        project.addDescriptor(installmentCharge);
        project.addDescriptor(chargePaidBy);
        project.addDescriptor(tx);
        project.addDescriptor(installment);
        project.addDescriptor(mapping);
        final DatabaseLogin login = new DatabaseLogin();
        login.setDriverClassName("org.h2.Driver");
        login.setConnectionString("jdbc:h2:mem:ls07_" + UUID.randomUUID());
        login.setUserName("sa");
        login.setPassword("");
        login.usePlatform(new H2Platform());
        project.setLogin(login);
        final DatabaseSession session = project.createDatabaseSession();
        session.setLogLevel(SessionLog.WARNING);
        session.login();
        session.executeNonSelectingSQL("CREATE TABLE LS07_LOAN (ID BIGINT PRIMARY KEY)");
        session.executeNonSelectingSQL("CREATE TABLE LS07_TX (ID BIGINT, LOAN_ID BIGINT, KIND VARCHAR(60), TX_DATE DATE, "
                + "AMOUNT DECIMAL(19,2), PRINCIPALPORTION DECIMAL(19,2), INTERESTPORTION DECIMAL(19,2), FEECHARGESPORTION DECIMAL(19,2), "
                + "PENALTYCHARGESPORTION DECIMAL(19,2), SOURCEEXACTALLOCATION BOOLEAN DEFAULT FALSE NOT NULL, SOURCEEXACTPRINCIPALPORTION DECIMAL(19,2), "
                + "SOURCEEXACTINTERESTPORTION DECIMAL(19,2), SOURCEEXACTFEECHARGESPORTION DECIMAL(19,2), SOURCEEXACTPENALTYCHARGESPORTION DECIMAL(19,2))");
        session.executeNonSelectingSQL("CREATE TABLE LS07_INSTALLMENT (ID BIGINT, LOAN_ID BIGINT NOT NULL, INSTALLMENT_NUMBER INT, "
                + "FROM_DATE DATE, DUE_DATE DATE, PRINCIPAL DECIMAL(19,2), INTERESTCHARGED DECIMAL(19,2), "
                + "PRINCIPALCOMPLETED DECIMAL(19,2), INTERESTPAID DECIMAL(19,2))");
        session.executeNonSelectingSQL("CREATE TABLE LS07_MAPPING (ID BIGINT, TX_ID BIGINT, INSTALLMENT_ID BIGINT, "
                + "AMOUNT DECIMAL(19,2), PRINCIPALPORTION DECIMAL(19,2), INTERESTPORTION DECIMAL(19,2), "
                + "FEECHARGESPORTION DECIMAL(19,2), PENALTYCHARGESPORTION DECIMAL(19,2))");
        session.executeNonSelectingSQL(
                "CREATE TABLE LS07_CHARGE (ID BIGINT, LOAN_ID BIGINT, AMOUNT DECIMAL(19,2), AMOUNTPAID DECIMAL(19,2), AMOUNTWAIVED DECIMAL(19,2), AMOUNTWRITTENOFF DECIMAL(19,2), AMOUNTOUTSTANDING DECIMAL(19,2), ACTIVE BOOLEAN, CHARGETIME INT, CHARGECALCULATION INT, DUE_DATE DATE)");
        session.executeNonSelectingSQL("CREATE TABLE LS07_INSTALLMENT_CHARGE (ID BIGINT, CHARGE_ID BIGINT)");
        session.executeNonSelectingSQL(
                "CREATE TABLE LS07_CHARGE_PAID_BY (ID BIGINT, CHARGE_ID BIGINT, TX_ID BIGINT, AMOUNT DECIMAL(19,2))");
        session.executeNonSelectingSQL("INSERT INTO LS07_CHARGE_PAID_BY VALUES(51,41,21,3)");
        session.executeNonSelectingSQL("INSERT INTO LS07_CHARGE VALUES(41,1,10,3,0,0,7,TRUE,2,1,DATE '2026-06-30')");
        session.executeNonSelectingSQL("INSERT INTO LS07_LOAN VALUES(1)");
        session.executeNonSelectingSQL("INSERT INTO LS07_INSTALLMENT VALUES(11,1,1,DATE '2026-06-01',DATE '2026-06-30',100,10,10,2)");
        session.executeNonSelectingSQL("INSERT INTO LS07_TX (ID,LOAN_ID,KIND,TX_DATE,AMOUNT,PRINCIPALPORTION,INTERESTPORTION) "
                + "VALUES(21,1,'REPAYMENT',DATE '2026-06-15',12,10,2)");
        session.executeNonSelectingSQL("INSERT INTO LS07_MAPPING VALUES(31,21,11,12,10,2,NULL,NULL)");
        return session;
    }

    private static RelationalDescriptor descriptor(Class<?> type, String table, String... fields) {
        final var descriptor = new RelationalDescriptor();
        descriptor.setJavaClass(type);
        descriptor.setTableName(table);
        descriptor.addPrimaryKeyFieldName("ID");
        descriptor.setObjectChangePolicy(new DeferredChangeDetectionPolicy());
        for (String field : fields)
            descriptor.addDirectMapping(field, field.toUpperCase(Locale.ROOT));
        return descriptor;
    }

    private static void owned(RelationalDescriptor owner, String field, Class<?> type, String foreignKey) {
        final var mapping = new OneToManyMapping();
        mapping.setAttributeName(field);
        mapping.setReferenceClass(type);
        mapping.dontUseIndirection();
        mapping.setIsPrivateOwned(true);
        mapping.addTargetForeignKeyFieldName(foreignKey, owner.getTableName() + ".ID");
        mapping.useCollectionClass(
                Set.class.isAssignableFrom(ReflectionUtils.findField(owner.getJavaClass(), field).getType()) ? HashSet.class
                        : ArrayList.class);
        owner.addMapping(mapping);
    }

    private static void reference(RelationalDescriptor owner, String field, Class<?> type, String foreignKey, String target,
            boolean cascade) {
        final var mapping = new OneToOneMapping();
        mapping.setAttributeName(field);
        mapping.setReferenceClass(type);
        mapping.dontUseIndirection();
        mapping.addForeignKeyFieldName(foreignKey, target);
        mapping.setCascadePersist(cascade);
        owner.addMapping(mapping);
    }
}
