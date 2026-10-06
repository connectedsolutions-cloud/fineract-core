package org.apache.fineract.portfolio.treasury.service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.common.AccountingConstants.FinancialActivity;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.financialactivityaccount.domain.FinancialActivityAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.glaccount.domain.GLAccountType;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.accounting.journalentry.service.AccountingProcessorHelper;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.staff.domain.Staff;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccount;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccountRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovement;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLine;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLink;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLinkRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementRepository;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class TreasuryMovementService {

    public static final String STATUS_POSTED = "posted";
    public static final String STATUS_REVERSED = "reversed";
    public static final String OWNER_TREASURY = "treasury";
    public static final String OWNER_NATIVE = "native";
    public static final String DIRECTION_DEBIT = "debit";
    public static final String DIRECTION_CREDIT = "credit";
    public static final String LINK_COMITE = "comite_session";
    public static final String LINK_LOAN = "loan_transaction";
    public static final String LINK_SAVINGS = "savings_transaction";
    public static final String LINK_STAFF = "staff";
    public static final String TYPE_OPENING = "opening_balance";
    public static final String TYPE_TRANSFER = "bank_transfer";
    public static final String TYPE_DEBIT = "bank_debit";
    public static final String TYPE_CREDIT = "bank_credit";
    public static final String TYPE_FUND_VAULT = "fund_vault";
    public static final String TYPE_VAULT_TO_BANK = "vault_to_bank";
    public static final String TYPE_COMITE = "comite_withdrawal";
    public static final String TYPE_SAVINGS_DEPOSIT = "savings_bank_deposit";
    public static final String TYPE_FD_PAYOUT = "fixed_deposit_maturity_payout";
    public static final String TYPE_LOAN_REPAYMENT = "loan_repayment";
    public static final String TYPE_EMPLOYEE = "employee_payment";
    public static final String TYPE_PROVIDER = "provider_payment";

    private final TreasuryBankAccountRepository bankAccountRepository;
    private final TreasuryMovementRepository movementRepository;
    private final TreasuryMovementLinkRepository linkRepository;
    private final GLAccountRepository glAccountRepository;
    private final OfficeRepositoryWrapper officeRepository;
    private final StaffRepository staffRepository;
    private final FinancialActivityAccountRepositoryWrapper financialActivityAccountRepository;
    private final AccountingProcessorHelper accountingProcessorHelper;
    private final AccountingCutoffPolicyService cutoffPolicyService;
    private final JournalReferenceNumberService journalReferenceNumberService;
    private final JournalEntryRepository journalEntryRepository;
    private final PlatformSecurityContext securityContext;

    @Transactional
    public TreasuryMovement post(TreasuryMovementCommand command) {
        requirePositive(command.amount());
        LocalDate businessDate = command.businessDate();
        rejectClosedPeriod(businessDate);
        LocalDate valueDate = command.valueDate() == null ? businessDate : command.valueDate();
        Office office = officeRepository.findOneWithNotFoundDetection(command.officeId());
        return switch (command.type()) {
            case TYPE_OPENING -> postOpening(command, office, businessDate, valueDate);
            case TYPE_TRANSFER -> postTransfer(command, office, businessDate, valueDate);
            case TYPE_DEBIT, TYPE_EMPLOYEE, TYPE_PROVIDER -> postBankCredit(command, office, businessDate, valueDate);
            case TYPE_CREDIT -> postBankDebit(command, office, businessDate, valueDate);
            case TYPE_FUND_VAULT, TYPE_COMITE -> postVaultFunding(command, office, businessDate, valueDate, command.type());
            case TYPE_VAULT_TO_BANK -> postVaultToBank(command, office, businessDate, valueDate);
            default -> throw rule("error.msg.treasury.movement.type.invalid", "Unknown treasury movement type");
        };
    }

    @Transactional
    public TreasuryMovement postComiteWithdrawal(SesionComite session, List<Loan> loans, Long bankAccountId, LocalDate businessDate) {
        if (session == null || session.getId() == null) {
            throw rule("error.msg.treasury.comite.session.required", "A comité session is required");
        }
        if (linkRepository.findByLinkTypeAndEntityId(LINK_COMITE, session.getId()).isPresent()) {
            throw rule("error.msg.treasury.comite.already.posted", "This comité session already has a bank withdrawal");
        }
        BigDecimal total = BigDecimal.ZERO;
        String currency = null;
        if (loans != null) {
            for (Loan loan : loans) {
                if (loan.getNetDisbursalAmount() != null) {
                    total = total.add(loan.getNetDisbursalAmount());
                }
                if (currency == null) {
                    currency = loan.getCurrencyCode();
                }
            }
        }
        if (total.compareTo(BigDecimal.ZERO) <= 0) {
            throw rule("error.msg.treasury.comite.amount.required", "The comité session has no cash disbursement amount");
        }
        Long officeId = session.getOffice() != null ? session.getOffice().getId() : null;
        if (officeId == null && loans != null && !loans.isEmpty() && loans.get(0).getOffice() != null) {
            officeId = loans.get(0).getOffice().getId();
        }
        TreasuryMovement movement = post(new TreasuryMovementCommand(TYPE_COMITE, businessDate, businessDate, officeId, total, null,
                bankAccountId, null, null, null, null, null, "Comité session " + session.getId()));
        if (currency != null && !currency.equals(movement.getCurrencyCode())) {
            throw rule("error.msg.treasury.currency.mismatch", "The bank account currency does not match the loans");
        }
        addLink(movement, LINK_COMITE, session.getId());
        return movementRepository.save(movement);
    }

    @Transactional
    public void recordNative(String movementType, String direction, Long bankAccountId, Long officeId, BigDecimal amount, String currency,
            LocalDate businessDate, String journalTransactionId, String linkType, Long entityId, String note) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            return;
        }
        if (linkRepository.findByLinkTypeAndEntityId(linkType, entityId).isPresent()) {
            return;
        }
        TreasuryBankAccount bank = lock(bankAccountId);
        if (!bank.getCurrencyCode().equals(currency)) {
            throw rule("error.msg.treasury.currency.mismatch", "The bank account currency does not match the transaction");
        }
        requireOpening(bank);
        Office office = officeRepository.findOneWithNotFoundDetection(officeId);
        TreasuryMovement movement = newMovement(movementType, office, businessDate, businessDate, amount, bank.getCurrencyCode(),
                OWNER_NATIVE, note, null, null, null, null);
        movement.setJournalTransactionId(journalTransactionId);
        movement.setRefNum(nativeReferenceNumber(journalTransactionId));
        movement.setStatus(STATUS_POSTED);
        applyLine(movement, bank, direction, amount);
        addLink(movement, linkType, entityId);
        movementRepository.save(movement);
    }

    @Transactional
    public void reverseNative(String linkType, Long entityId) {
        TreasuryMovementLink link = linkRepository.findByLinkTypeAndEntityId(linkType, entityId).orElse(null);
        if (link == null) {
            return;
        }
        TreasuryMovement movement = link.getMovement();
        if (!STATUS_POSTED.equals(movement.getStatus()) || !OWNER_NATIVE.equals(movement.getJournalOwner())) {
            return;
        }
        restoreLines(movement);
        movement.setStatus(STATUS_REVERSED);
        movementRepository.save(movement);
    }

    @Transactional
    public TreasuryMovement reverse(Long movementId) {
        TreasuryMovement original = movementRepository.findById(movementId)
                .orElseThrow(() -> rule("error.msg.treasury.movement.not.found", "Treasury movement was not found"));
        if (!OWNER_TREASURY.equals(original.getJournalOwner())) {
            throw rule("error.msg.treasury.reverse.native.forbidden",
                    "Reverse the savings, deposit, or loan transaction that owns this bank line");
        }
        if (!STATUS_POSTED.equals(original.getStatus())) {
            throw rule("error.msg.treasury.movement.already.reversed", "This treasury movement is already reversed");
        }
        rejectClosedPeriod(DateUtils.getBusinessLocalDate());
        List<TreasuryMovementLine> originalLines = new ArrayList<>(original.getLines());
        for (TreasuryMovementLine line : originalLines) {
            if (TYPE_OPENING.equals(original.getMovementType())
                    && movementRepository.countLines(line.getBankAccount().getId()) > originalLines.size()) {
                throw rule("error.msg.treasury.opening.reverse.blocked",
                        "Reverse the later movements before reversing the opening balance");
            }
        }
        TreasuryMovement reversal = newMovement(original.getMovementType(), original.getOffice(), DateUtils.getBusinessLocalDate(),
                DateUtils.getBusinessLocalDate(), original.getAmount(), original.getCurrencyCode(), OWNER_TREASURY,
                "Reversal of movement " + original.getId(), original.getBankReference(), original.getPayeeName(), original.getStaff(),
                original.getCounterGlAccount());
        reversal.setReversesMovementId(original.getId());
        reversal = movementRepository.saveAndFlush(reversal);
        String transactionId = "TRS-" + reversal.getId();
        reversal.setJournalTransactionId(transactionId);
        String refNum = journalReferenceNumberService.assign(transactionId + "|" + reversal.getBusinessDate(), reversal.getBusinessDate());
        reversal.setRefNum(refNum);
        List<Long> bankIds = originalLines.stream().map(line -> line.getBankAccount().getId()).distinct().sorted().toList();
        List<TreasuryBankAccount> locked = new ArrayList<>();
        for (Long bankId : bankIds) {
            locked.add(lock(bankId));
        }
        for (TreasuryMovementLine line : originalLines) {
            TreasuryBankAccount bank = locked.stream().filter(item -> item.getId().equals(line.getBankAccount().getId())).findFirst()
                    .orElseThrow();
            String opposite = DIRECTION_DEBIT.equals(line.getDirection()) ? DIRECTION_CREDIT : DIRECTION_DEBIT;
            applyLine(reversal, bank, opposite, line.getAmount());
        }
        postReversalJournal(original, originalLines, reversal, transactionId, refNum);
        original.setStatus(STATUS_REVERSED);
        movementRepository.save(original);
        return movementRepository.save(reversal);
    }

    private TreasuryMovement postOpening(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate) {
        TreasuryBankAccount bank = lock(command.bankAccountId());
        if (movementRepository.countLines(bank.getId()) > 0) {
            throw rule("error.msg.treasury.opening.not.first", "An opening balance must be the first movement on the bank");
        }
        String direction = command.direction() == null ? DIRECTION_DEBIT : command.direction();
        if (!DIRECTION_DEBIT.equals(direction) && !DIRECTION_CREDIT.equals(direction)) {
            throw rule("error.msg.treasury.direction.invalid", "Opening balance direction must be debit or credit");
        }
        GLAccount contra = financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.OPENING_BALANCES_TRANSFER_CONTRA.getValue())
                .getGlAccount();
        return postSingleBank(TYPE_OPENING, bank, office, businessDate, valueDate, command.amount(), direction, contra, command, null);
    }

    private TreasuryMovement postTransfer(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate) {
        if (command.bankAccountId().equals(command.destinationBankAccountId())) {
            throw rule("error.msg.treasury.transfer.same.bank", "A transfer needs two different bank accounts");
        }
        List<Long> ids = List.of(command.bankAccountId(), command.destinationBankAccountId()).stream().sorted().toList();
        TreasuryBankAccount first = lock(ids.get(0));
        TreasuryBankAccount second = lock(ids.get(1));
        TreasuryBankAccount source = first.getId().equals(command.bankAccountId()) ? first : second;
        TreasuryBankAccount destination = first.getId().equals(command.destinationBankAccountId()) ? first : second;
        requireActive(source);
        requireActive(destination);
        requireOpening(source);
        requireOpening(destination);
        if (!source.getCurrencyCode().equals(destination.getCurrencyCode())) {
            throw rule("error.msg.treasury.currency.mismatch", "Both bank accounts must use the same currency");
        }
        TreasuryMovement movement = newMovement(TYPE_TRANSFER, office, businessDate, valueDate, command.amount(), source.getCurrencyCode(),
                OWNER_TREASURY, command.note(), command.bankReference(), null, null, null);
        movement = movementRepository.saveAndFlush(movement);
        String transactionId = "TRS-" + movement.getId();
        String refNum = journalReferenceNumberService.assign(transactionId + "|" + businessDate, businessDate);
        movement.setJournalTransactionId(transactionId);
        movement.setRefNum(refNum);
        applyLine(movement, source, DIRECTION_CREDIT, command.amount());
        applyLine(movement, destination, DIRECTION_DEBIT, command.amount());
        persistJournal(office, source.getCurrencyCode(), source.getGlAccount(), transactionId, businessDate, JournalEntryType.CREDIT,
                command.amount(), refNum, movement.getNote());
        persistJournal(office, destination.getCurrencyCode(), destination.getGlAccount(), transactionId, businessDate,
                JournalEntryType.DEBIT, command.amount(), refNum, movement.getNote());
        return movementRepository.save(movement);
    }

    private TreasuryMovement postBankCredit(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate) {
        if (TYPE_PROVIDER.equals(command.type()) && (command.payeeName() == null || command.payeeName().isBlank())) {
            throw rule("error.msg.treasury.payee.required", "A provider or service payment needs a payee");
        }
        TreasuryBankAccount bank = prepareBank(command.bankAccountId());
        GLAccount counter = requireCounter(command.counterGlAccountId(), bank);
        Staff staff = resolveStaff(command.staffId());
        TreasuryMovement movement = postSingleBank(command.type(), bank, office, businessDate, valueDate, command.amount(),
                DIRECTION_CREDIT, counter, command, staff);
        if (staff != null) {
            addLink(movement, LINK_STAFF, staff.getId());
        }
        return movementRepository.save(movement);
    }

    private TreasuryMovement postBankDebit(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate) {
        TreasuryBankAccount bank = prepareBank(command.bankAccountId());
        GLAccount counter = requireCounter(command.counterGlAccountId(), bank);
        return postSingleBank(TYPE_CREDIT, bank, office, businessDate, valueDate, command.amount(), DIRECTION_DEBIT, counter, command,
                null);
    }

    private TreasuryMovement postVaultFunding(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate,
            String type) {
        TreasuryBankAccount bank = prepareBank(command.bankAccountId());
        GLAccount vault = vaultAccount();
        return postSingleBank(type, bank, office, businessDate, valueDate, command.amount(), DIRECTION_CREDIT, vault, command, null);
    }

    private TreasuryMovement postVaultToBank(TreasuryMovementCommand command, Office office, LocalDate businessDate, LocalDate valueDate) {
        TreasuryBankAccount bank = prepareBank(command.bankAccountId());
        GLAccount vault = vaultAccount();
        return postSingleBank(TYPE_VAULT_TO_BANK, bank, office, businessDate, valueDate, command.amount(), DIRECTION_DEBIT, vault,
                command, null);
    }

    private TreasuryMovement postSingleBank(String type, TreasuryBankAccount bank, Office office, LocalDate businessDate,
            LocalDate valueDate, BigDecimal amount, String bankDirection, GLAccount otherSide, TreasuryMovementCommand command,
            Staff staff) {
        TreasuryMovement movement = newMovement(type, office, businessDate, valueDate, amount, bank.getCurrencyCode(), OWNER_TREASURY,
                command.note(), command.bankReference(), command.payeeName(), staff, otherSide);
        movement = movementRepository.saveAndFlush(movement);
        String transactionId = "TRS-" + movement.getId();
        String refNum = journalReferenceNumberService.assign(transactionId + "|" + businessDate, businessDate);
        movement.setJournalTransactionId(transactionId);
        movement.setRefNum(refNum);
        applyLine(movement, bank, bankDirection, amount);
        postPair(office, bank.getCurrencyCode(), transactionId, businessDate, refNum, bank.getGlAccount(), otherSide, amount,
                bankDirection);
        return movementRepository.save(movement);
    }

    private void postPair(Office office, String currency, String transactionId, LocalDate date, String refNum, GLAccount bankGl,
            GLAccount other, BigDecimal amount, String bankDirection) {
        JournalEntryType bankType = DIRECTION_DEBIT.equals(bankDirection) ? JournalEntryType.DEBIT : JournalEntryType.CREDIT;
        JournalEntryType otherType = bankType == JournalEntryType.DEBIT ? JournalEntryType.CREDIT : JournalEntryType.DEBIT;
        persistJournal(office, currency, bankGl, transactionId, date, bankType, amount, refNum, null);
        persistJournal(office, currency, other, transactionId, date, otherType, amount, refNum, null);
    }

    private void postReversalJournal(TreasuryMovement original, List<TreasuryMovementLine> originalLines, TreasuryMovement reversal,
            String transactionId, String refNum) {
        if (TYPE_TRANSFER.equals(original.getMovementType())) {
            TreasuryMovementLine credited = originalLines.stream().filter(line -> DIRECTION_CREDIT.equals(line.getDirection())).findFirst()
                    .orElseThrow();
            TreasuryMovementLine debited = originalLines.stream().filter(line -> DIRECTION_DEBIT.equals(line.getDirection())).findFirst()
                    .orElseThrow();
            postPair(reversal.getOffice(), reversal.getCurrencyCode(), transactionId, reversal.getBusinessDate(), refNum,
                    credited.getBankAccount().getGlAccount(), debited.getBankAccount().getGlAccount(), original.getAmount(),
                    DIRECTION_DEBIT);
            return;
        }
        TreasuryMovementLine line = originalLines.get(0);
        String opposite = DIRECTION_DEBIT.equals(line.getDirection()) ? DIRECTION_CREDIT : DIRECTION_DEBIT;
        GLAccount other = oppositeGl(original, line);
        postPair(reversal.getOffice(), reversal.getCurrencyCode(), transactionId, reversal.getBusinessDate(), refNum,
                line.getBankAccount().getGlAccount(), other, line.getAmount(), opposite);
    }

    private GLAccount oppositeGl(TreasuryMovement original, TreasuryMovementLine line) {
        if (TYPE_TRANSFER.equals(original.getMovementType())) {
            return original.getLines().stream().filter(other -> !other.getBankAccount().getId().equals(line.getBankAccount().getId()))
                    .map(other -> other.getBankAccount().getGlAccount()).findFirst().orElseThrow();
        }
        if (original.getCounterGlAccount() != null) {
            return original.getCounterGlAccount();
        }
        if (TYPE_OPENING.equals(original.getMovementType())) {
            return financialActivityAccountRepository
                    .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.OPENING_BALANCES_TRANSFER_CONTRA.getValue())
                    .getGlAccount();
        }
        return vaultAccount();
    }

    private void persistJournal(Office office, String currency, GLAccount account, String transactionId, LocalDate date,
            JournalEntryType type, BigDecimal amount, String refNum, String description) {
        JournalEntry entry = JournalEntry.createNew(office, null, account, currency, transactionId, false, date, type, amount, description,
                null, null, refNum, null, null, null, null, null);
        accountingProcessorHelper.persistJournalEntry(entry);
    }

    private TreasuryBankAccount prepareBank(Long bankAccountId) {
        TreasuryBankAccount bank = lock(bankAccountId);
        requireActive(bank);
        requireOpening(bank);
        return bank;
    }

    private TreasuryBankAccount lock(Long bankAccountId) {
        if (bankAccountId == null) {
            throw rule("error.msg.treasury.bank.required", "A treasury bank account is required");
        }
        return bankAccountRepository.findByIdForUpdate(bankAccountId)
                .orElseThrow(() -> rule("error.msg.treasury.bank.not.found", "Treasury bank account was not found"));
    }

    private void requireActive(TreasuryBankAccount bank) {
        if (!bank.isActive()) {
            throw rule("error.msg.treasury.bank.inactive", "The treasury bank account is inactive");
        }
    }

    private void requireOpening(TreasuryBankAccount bank) {
        if (movementRepository.countPostedOpeningLines(bank.getId()) == 0) {
            throw rule("error.msg.treasury.opening.required", "Post an opening balance before other movements on this bank");
        }
    }

    private GLAccount requireCounter(Long counterGlAccountId, TreasuryBankAccount bank) {
        if (counterGlAccountId == null) {
            throw rule("error.msg.treasury.counter.gl.required", "Choose the other general ledger account");
        }
        GLAccount counter = glAccountRepository.findById(counterGlAccountId)
                .orElseThrow(() -> rule("error.msg.treasury.counter.gl.not.found", "The counter account was not found"));
        if (counter.isDisabled() || !counter.isDetailAccount()) {
            throw rule("error.msg.treasury.counter.gl.invalid", "The counter account must be an enabled detail account");
        }
        if (bankAccountRepository.existsByGlAccountId(counter.getId()) || counter.getId().equals(bank.getGlAccount().getId())) {
            throw rule("error.msg.treasury.counter.gl.is.bank", "Use a transfer when the other side is a bank account");
        }
        if (counter.getId().equals(vaultAccount().getId())) {
            throw rule("error.msg.treasury.counter.gl.is.vault", "Use fund vault or vault to bank for the vault account");
        }
        return counter;
    }

    private GLAccount vaultAccount() {
        return financialActivityAccountRepository
                .findByFinancialActivityTypeWithNotFoundDetection(FinancialActivity.CASH_AT_MAINVAULT.getValue()).getGlAccount();
    }

    private Staff resolveStaff(Long staffId) {
        if (staffId == null) {
            return null;
        }
        return staffRepository.findById(staffId)
                .orElseThrow(() -> rule("error.msg.treasury.staff.not.found", "The employee was not found"));
    }

    private TreasuryMovement newMovement(String type, Office office, LocalDate businessDate, LocalDate valueDate, BigDecimal amount,
            String currency, String owner, String note, String bankReference, String payee, Staff staff, GLAccount counter) {
        TreasuryMovement movement = new TreasuryMovement();
        movement.setMovementType(type);
        movement.setOffice(office);
        movement.setBusinessDate(businessDate);
        movement.setValueDate(valueDate);
        movement.setAmount(amount);
        movement.setCurrencyCode(currency);
        movement.setStatus(STATUS_POSTED);
        movement.setJournalOwner(owner);
        movement.setNote(note);
        movement.setBankReference(bankReference);
        movement.setPayeeName(payee);
        movement.setStaff(staff);
        movement.setCounterGlAccount(counter);
        movement.setCreatedByUserId(currentUserId());
        movement.setCreatedOn(OffsetDateTime.now());
        return movement;
    }

    private void applyLine(TreasuryMovement movement, TreasuryBankAccount bank, String direction, BigDecimal amount) {
        BigDecimal signed = DIRECTION_DEBIT.equals(direction) ? amount : amount.negate();
        BigDecimal balance = bank.getBalance() == null ? BigDecimal.ZERO : bank.getBalance();
        balance = balance.add(signed);
        bank.setBalance(balance);
        bankAccountRepository.save(bank);
        TreasuryMovementLine line = new TreasuryMovementLine();
        line.setMovement(movement);
        line.setBankAccount(bank);
        line.setDirection(direction);
        line.setAmount(amount);
        line.setBalanceAfter(balance);
        movement.getLines().add(line);
    }

    private void restoreLines(TreasuryMovement movement) {
        List<TreasuryMovementLine> lines = movement.getLines().stream()
                .sorted(Comparator.comparing(line -> line.getBankAccount().getId())).toList();
        List<Long> bankIds = lines.stream().map(line -> line.getBankAccount().getId()).distinct().sorted().toList();
        for (Long bankId : bankIds) {
            lock(bankId);
        }
        for (TreasuryMovementLine line : lines) {
            TreasuryBankAccount bank = lock(line.getBankAccount().getId());
            String opposite = DIRECTION_DEBIT.equals(line.getDirection()) ? DIRECTION_CREDIT : DIRECTION_DEBIT;
            applyLine(movement, bank, opposite, line.getAmount());
        }
    }

    private void addLink(TreasuryMovement movement, String linkType, Long entityId) {
        TreasuryMovementLink link = new TreasuryMovementLink();
        link.setMovement(movement);
        link.setLinkType(linkType);
        link.setEntityId(entityId);
        movement.getLinks().add(link);
    }

    private void requirePositive(BigDecimal amount) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw rule("error.msg.treasury.amount.positive", "The amount must be greater than zero");
        }
    }

    private void rejectClosedPeriod(LocalDate date) {
        if (!cutoffPolicyService.shouldGenerateAccounting(date)) {
            throw rule("error.msg.treasury.period.closed", "Accounting is closed for this date");
        }
    }

    private String nativeReferenceNumber(String journalTransactionId) {
        if (journalTransactionId == null) {
            return null;
        }
        List<String> numbers = journalEntryRepository.findReferenceNumbersByTransactionId(journalTransactionId);
        if (numbers == null || numbers.isEmpty()) {
            return null;
        }
        return numbers.get(0);
    }

    private Long currentUserId() {
        try {
            AppUser user = securityContext.authenticatedUser();
            return user == null ? null : user.getId();
        } catch (RuntimeException ex) {
            return null;
        }
    }

    public static GeneralPlatformDomainRuleException rule(String code, String message) {
        return new GeneralPlatformDomainRuleException(code, message);
    }

    public static boolean isAssetDetail(GLAccount account) {
        return account != null && !account.isDisabled() && account.isDetailAccount()
                && GLAccountType.ASSET.getValue().equals(account.getType());
    }
}
