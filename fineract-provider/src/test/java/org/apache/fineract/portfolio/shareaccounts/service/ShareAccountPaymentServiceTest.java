package org.apache.fineract.portfolio.shareaccounts.service;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.apache.fineract.accounting.common.AccountingConstants.CashAccountsForShares;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.accounting.journalentry.service.JournalEntryWritePlatformService;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.organisation.teller.domain.Teller;
import org.apache.fineract.portfolio.paymentdetail.domain.PaymentDetail;
import org.apache.fineract.portfolio.paymentdetail.domain.PaymentDetailRepository;
import org.apache.fineract.portfolio.paymenttype.domain.PaymentType;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccount;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountRepositoryWrapper;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountStatusType;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccountTransaction;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificate;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareCertificateRepository;
import org.apache.fineract.portfolio.shareproducts.domain.ShareProduct;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ShareAccountPaymentServiceTest {

    private static final LocalDate PAYMENT_DATE = LocalDate.of(2026, 10, 13);

    @Mock
    private ShareAccountRepositoryWrapper shareAccountRepository;
    @Mock
    private PaymentDetailRepository paymentDetailRepository;
    @Mock
    private CashierRepository cashierRepository;
    @Mock
    private CashierTransactionRepository cashierTransactionRepository;
    @Mock
    private AccountingProcessorHelper accountingProcessorHelper;
    @Mock
    private AccountingCutoffPolicyService cutoffPolicyService;
    @Mock
    private JournalEntryWritePlatformService journalEntryWritePlatformService;
    @Mock
    private ShareCertificateService shareCertificateService;
    @Mock
    private ShareCertificateRepository shareCertificateRepository;
    @Mock
    private PlatformSecurityContext platformSecurityContext;
    @Mock
    private ShareAccount account;
    @Mock
    private ShareAccountTransaction purchase;
    @Mock
    private ShareProduct shareProduct;
    @Mock
    private MonetaryCurrency currency;
    @Mock
    private AppUser user;

    private ShareAccountPaymentService service;

    @BeforeEach
    void setUp() {
        this.service = new ShareAccountPaymentService(shareAccountRepository, paymentDetailRepository, cashierRepository,
                cashierTransactionRepository, accountingProcessorHelper, cutoffPolicyService, journalEntryWritePlatformService,
                shareCertificateService, shareCertificateRepository, platformSecurityContext);
    }

    @Test
    void paymentIsRejectedWhileSubmitted() {
        when(shareAccountRepository.findOneWithNotFoundDetection(8L)).thenReturn(account);
        when(account.status()).thenReturn(ShareAccountStatusType.SUBMITTED_AND_PENDING_APPROVAL.getValue());
        PaymentDetail payment = chequePayment(false);

        assertThrows(GeneralPlatformDomainRuleException.class, () -> service.recordChannelPayment(8L, PAYMENT_DATE, payment));
        verify(accountingProcessorHelper, never()).createShareFundingJournalEntry(any(), any(), any(), any(), any(), any(), any(), any(),
                any());
    }

    @Test
    void cashPaymentTypeIsRejectedOnMarkPaid() {
        assertThrows(GeneralPlatformDomainRuleException.class,
                () -> service.recordChannelPayment(8L, PAYMENT_DATE, chequePayment(true)));
        verify(shareAccountRepository, never()).findOneWithNotFoundDetection(any());
    }

    @Test
    void chequePaymentPostsBankDebitAndEmitsCertificate() {
        approvedAccount();
        PaymentDetail payment = chequePayment(false);
        when(payment.getPaymentType().getId()).thenReturn(4L);
        when(paymentDetailRepository.save(payment)).thenReturn(payment);
        when(cutoffPolicyService.shouldGenerateAccounting(PAYMENT_DATE)).thenReturn(true);
        GLAccount bank = org.mockito.Mockito.mock(GLAccount.class);
        GLAccount equity = org.mockito.Mockito.mock(GLAccount.class);
        Office office = org.mockito.Mockito.mock(Office.class);
        when(accountingProcessorHelper.getOfficeById(1L)).thenReturn(office);
        when(accountingProcessorHelper.getShareProductGLAccount(3L, CashAccountsForShares.SHARES_REFERENCE.getValue(), 4L))
                .thenReturn(bank);
        when(accountingProcessorHelper.getShareProductGLAccount(3L, CashAccountsForShares.SHARES_EQUITY.getValue(), null))
                .thenReturn(equity);
        ShareCertificate certificate = org.mockito.Mockito.mock(ShareCertificate.class);
        when(certificate.getNativeStatus()).thenReturn(ShareCertificate.STATUS_OPENED);
        when(certificate.getId()).thenReturn(11L);
        when(shareCertificateRepository.findByShareAccountIdOrderByIdAsc(8L)).thenReturn(List.of(certificate));
        when(platformSecurityContext.authenticatedUser()).thenReturn(user);

        service.recordChannelPayment(8L, PAYMENT_DATE, payment);

        verify(accountingProcessorHelper).createShareFundingJournalEntry(office, "USD", bank, equity, 8L, "9", PAYMENT_DATE,
                new BigDecimal("100.00"), payment);
        verify(account).activate(PAYMENT_DATE, user);
        verify(shareCertificateService).emit(11L);
    }

    @Test
    void tellerCashPostsTellerCashDebit() {
        approvedAccount();
        when(cutoffPolicyService.shouldGenerateAccounting(PAYMENT_DATE)).thenReturn(true);
        Cashier cashier = org.mockito.Mockito.mock(Cashier.class);
        Teller teller = org.mockito.Mockito.mock(Teller.class);
        Office cashierOffice = org.mockito.Mockito.mock(Office.class);
        when(cashier.getTeller()).thenReturn(teller);
        when(teller.getOffice()).thenReturn(cashierOffice);
        when(cashierOffice.getId()).thenReturn(1L);
        when(cashierRepository.findById(7L)).thenReturn(Optional.of(cashier));
        when(cashierTransactionRepository.saveAndFlush(any(CashierTransaction.class))).thenAnswer(invocation -> invocation.getArgument(0));
        GLAccount cash = org.mockito.Mockito.mock(GLAccount.class);
        GLAccount equity = org.mockito.Mockito.mock(GLAccount.class);
        Office office = org.mockito.Mockito.mock(Office.class);
        when(accountingProcessorHelper.getCashAtTellerGLAccount()).thenReturn(cash);
        when(accountingProcessorHelper.getOfficeById(1L)).thenReturn(office);
        when(accountingProcessorHelper.getShareProductGLAccount(eq(3L), eq(CashAccountsForShares.SHARES_EQUITY.getValue()), isNull()))
                .thenReturn(equity);
        when(shareCertificateRepository.findByShareAccountIdOrderByIdAsc(8L)).thenReturn(List.of());
        when(platformSecurityContext.authenticatedUser()).thenReturn(user);

        service.recordCashierPayment(8L, PAYMENT_DATE, 7L, "cash");

        verify(accountingProcessorHelper).createShareFundingJournalEntry(eq(office), eq("USD"), eq(cash), eq(equity), eq(8L), eq("9"),
                eq(PAYMENT_DATE), eq(new BigDecimal("100.00")), isNull());
        verify(account).activate(PAYMENT_DATE, user);
    }

    @Test
    void undoPaymentReopensCertificateAndReversesJournal() {
        when(shareAccountRepository.findOneWithNotFoundDetection(8L)).thenReturn(account);
        when(account.status()).thenReturn(ShareAccountStatusType.ACTIVE.getValue());
        when(account.getShareAccountTransactions()).thenReturn(Set.of(purchase));
        when(account.getChargeTransactions()).thenReturn(Set.of());
        when(account.getClientId()).thenReturn(2L);
        when(purchase.isActive()).thenReturn(true);
        when(purchase.isPurchasTransaction()).thenReturn(true);
        when(purchase.isRedeemTransaction()).thenReturn(false);
        when(purchase.getId()).thenReturn(9L);
        PaymentDetail payment = chequePayment(false);
        when(purchase.getPaymentDetail()).thenReturn(payment);
        when(purchase.getCashierTransactionId()).thenReturn(null);

        service.undoPayment(8L, PAYMENT_DATE);

        verify(shareCertificateService).reopenUnprinted(8L);
        verify(journalEntryWritePlatformService).revertShareAccountJournalEntries(any(), eq(PAYMENT_DATE));
        verify(purchase).clearRecordedPayment();
        verify(account).undoActivation();
    }

    private void approvedAccount() {
        when(shareAccountRepository.findOneWithNotFoundDetection(8L)).thenReturn(account);
        when(account.status()).thenReturn(ShareAccountStatusType.APPROVED.getValue());
        when(account.getShareAccountTransactions()).thenReturn(Set.of(purchase));
        when(account.getShareProduct()).thenReturn(shareProduct);
        when(account.getOfficeId()).thenReturn(1L);
        when(account.getCurrency()).thenReturn(currency);
        when(account.getId()).thenReturn(8L);
        when(account.getClientId()).thenReturn(2L);
        when(shareProduct.getId()).thenReturn(3L);
        when(shareProduct.getAccountingType()).thenReturn(2);
        when(currency.getCode()).thenReturn("USD");
        when(purchase.isActive()).thenReturn(true);
        when(purchase.isPurchasTransaction()).thenReturn(true);
        when(purchase.amount()).thenReturn(new BigDecimal("100.00"));
        when(purchase.getId()).thenReturn(9L);
        when(purchase.getPaymentDetail()).thenReturn(null);
        when(purchase.getCashierTransactionId()).thenReturn(null);
    }

    private PaymentDetail chequePayment(boolean cash) {
        PaymentType paymentType = org.mockito.Mockito.mock(PaymentType.class);
        lenient().when(paymentType.getIsCashPayment()).thenReturn(cash);
        return PaymentDetail.instance(paymentType, null, "1001", null, null, null);
    }
}
