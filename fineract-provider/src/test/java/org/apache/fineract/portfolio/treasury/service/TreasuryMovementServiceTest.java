package org.apache.fineract.portfolio.treasury.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Optional;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccount;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccountRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovement;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLink;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLinkRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class TreasuryMovementServiceTest {

    private final TreasuryBankAccountRepository bankAccountRepository = mock(TreasuryBankAccountRepository.class);
    private final TreasuryMovementRepository movementRepository = mock(TreasuryMovementRepository.class);
    private final TreasuryMovementLinkRepository linkRepository = mock(TreasuryMovementLinkRepository.class);
    private final OfficeRepositoryWrapper officeRepository = mock(OfficeRepositoryWrapper.class);
    private final AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);
    private final PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
    private TreasuryMovementService service;
    private TreasuryBankAccount bank;

    @BeforeEach
    void setUp() {
        service = new TreasuryMovementService(bankAccountRepository, movementRepository, linkRepository, mock(GLAccountRepository.class),
                officeRepository, mock(StaffRepository.class), mock(FinancialActivityAccountRepositoryWrapper.class),
                mock(AccountingProcessorHelper.class), cutoffPolicyService, mock(JournalReferenceNumberService.class),
                mock(JournalEntryRepository.class), securityContext);
        bank = new TreasuryBankAccount();
        bank.setId(1L);
        bank.setCurrencyCode("USD");
        bank.setActive(true);
        bank.setBalance(BigDecimal.ZERO);
        when(bankAccountRepository.findByIdForUpdate(1L)).thenReturn(Optional.of(bank));
        when(officeRepository.findOneWithNotFoundDetection(7L)).thenReturn(mock(Office.class));
        when(cutoffPolicyService.shouldGenerateAccounting(any())).thenReturn(true);
        when(securityContext.authenticatedUser()).thenThrow(new RuntimeException("no user"));
        when(linkRepository.findByLinkTypeAndEntityId(any(), any())).thenReturn(Optional.empty());
        when(movementRepository.countPostedOpeningLines(1L)).thenReturn(1L);
        when(movementRepository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(bankAccountRepository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void secondMovementSeesTheFirstRunningBalance() {
        service.recordNative(TreasuryMovementService.TYPE_SAVINGS_DEPOSIT, TreasuryMovementService.DIRECTION_DEBIT, 1L, 7L,
                new BigDecimal("100.00"), "USD", LocalDate.of(2026, 9, 25), "S1", TreasuryMovementService.LINK_SAVINGS, 1L, null);
        service.recordNative(TreasuryMovementService.TYPE_LOAN_REPAYMENT, TreasuryMovementService.DIRECTION_DEBIT, 1L, 7L,
                new BigDecimal("40.00"), "USD", LocalDate.of(2026, 9, 25), "L2", TreasuryMovementService.LINK_LOAN, 2L, null);

        assertEquals(new BigDecimal("140.00"), bank.getBalance());
    }

    @Test
    void openingBalanceIsRejectedAfterAnotherMovement() {
        when(movementRepository.countLines(1L)).thenReturn(1L);
        TreasuryMovementCommand command = new TreasuryMovementCommand(TreasuryMovementService.TYPE_OPENING, LocalDate.of(2026, 9, 25),
                null, 7L, new BigDecimal("10.00"), "debit", 1L, null, null, null, null, null, null);

        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.post(command));
    }

    @Test
    void nativeOwnedMovementCannotBeReversedFromTreasury() {
        TreasuryMovement movement = new TreasuryMovement();
        movement.setJournalOwner(TreasuryMovementService.OWNER_NATIVE);
        movement.setStatus(TreasuryMovementService.STATUS_POSTED);
        when(movementRepository.findById(9L)).thenReturn(Optional.of(movement));

        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.reverse(9L));
    }

    @Test
    void closedPeriodIsRejected() {
        when(cutoffPolicyService.shouldGenerateAccounting(any())).thenReturn(false);
        TreasuryMovementCommand command = new TreasuryMovementCommand(TreasuryMovementService.TYPE_OPENING, LocalDate.of(2026, 9, 25),
                null, 7L, new BigDecimal("10.00"), "debit", 1L, null, null, null, null, null, null);

        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.post(command));
    }

    @Test
    void reversingANativeLineRestoresTheBankBalance() {
        org.mockito.ArgumentCaptor<TreasuryMovement> captor = org.mockito.ArgumentCaptor.forClass(TreasuryMovement.class);
        when(movementRepository.save(captor.capture())).thenAnswer(invocation -> invocation.getArgument(0));
        service.recordNative(TreasuryMovementService.TYPE_SAVINGS_DEPOSIT, TreasuryMovementService.DIRECTION_DEBIT, 1L, 7L,
                new BigDecimal("100.00"), "USD", LocalDate.of(2026, 9, 25), "S1", TreasuryMovementService.LINK_SAVINGS, 1L, null);
        TreasuryMovement posted = captor.getValue();
        TreasuryMovementLink link = new TreasuryMovementLink();
        link.setMovement(posted);
        when(linkRepository.findByLinkTypeAndEntityId(TreasuryMovementService.LINK_SAVINGS, 1L)).thenReturn(Optional.of(link));

        service.reverseNative(TreasuryMovementService.LINK_SAVINGS, 1L);

        assertEquals(0, bank.getBalance().compareTo(BigDecimal.ZERO));
        assertEquals(TreasuryMovementService.STATUS_REVERSED, posted.getStatus());
    }
}
