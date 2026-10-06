package org.apache.fineract.portfolio.treasury.service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccount;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccountRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class TreasuryBankAccountService {

    private final TreasuryBankAccountRepository bankAccountRepository;
    private final GLAccountRepository glAccountRepository;
    private final OfficeRepositoryWrapper officeRepository;
    private final PlatformSecurityContext securityContext;

    @Transactional(readOnly = true)
    public List<TreasuryBankAccount> list(boolean activeOnly) {
        return activeOnly ? bankAccountRepository.findByActiveTrueOrderByNameAsc() : bankAccountRepository.findAllByOrderByNameAsc();
    }

    @Transactional(readOnly = true)
    public TreasuryBankAccount get(Long id) {
        return bankAccountRepository.findById(id)
                .orElseThrow(() -> TreasuryMovementService.rule("error.msg.treasury.bank.not.found", "Treasury bank account was not found"));
    }

    @Transactional
    public TreasuryBankAccount create(String name, Long glAccountId, String currencyCode, Long officeId, String externalReference,
            String alias) {
        if (externalReference == null || externalReference.isBlank()) {
            throw TreasuryMovementService.rule("error.msg.treasury.bank.account.number.required", "The bank account number is required");
        }
        GLAccount glAccount = requireBankGl(glAccountId);
        if (bankAccountRepository.existsByGlAccountId(glAccountId)) {
            throw TreasuryMovementService.rule("error.msg.treasury.bank.gl.duplicate", "That general ledger account is already a bank");
        }
        TreasuryBankAccount bank = new TreasuryBankAccount();
        bank.setName(name);
        bank.setGlAccount(glAccount);
        bank.setCurrencyCode(currencyCode);
        bank.setOffice(office(officeId));
        bank.setExternalAccountReference(externalReference.trim());
        bank.setAlias(blankToNull(alias));
        bank.setActive(true);
        bank.setBalance(BigDecimal.ZERO);
        bank.setCreatedOn(OffsetDateTime.now());
        try {
            bank.setCreatedByUserId(securityContext.authenticatedUser().getId());
        } catch (RuntimeException ex) {
            bank.setCreatedByUserId(null);
        }
        return bankAccountRepository.save(bank);
    }

    @Transactional
    public TreasuryBankAccount update(Long id, String name, Long officeId, String externalReference, String alias, Boolean active) {
        TreasuryBankAccount bank = get(id);
        if (name != null && !name.isBlank()) {
            bank.setName(name);
        }
        if (officeId != null) {
            bank.setOffice(office(officeId));
        }
        if (externalReference != null) {
            if (externalReference.isBlank()) {
                throw TreasuryMovementService.rule("error.msg.treasury.bank.account.number.required", "The bank account number is required");
            }
            bank.setExternalAccountReference(externalReference.trim());
        }
        if (alias != null) {
            bank.setAlias(blankToNull(alias));
        }
        if (active != null) {
            bank.setActive(active);
        }
        return bankAccountRepository.save(bank);
    }

    private String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private GLAccount requireBankGl(Long glAccountId) {
        GLAccount glAccount = glAccountRepository.findById(glAccountId).orElseThrow(
                () -> TreasuryMovementService.rule("error.msg.treasury.bank.gl.not.found", "The general ledger account was not found"));
        if (!TreasuryMovementService.isAssetDetail(glAccount)) {
            throw TreasuryMovementService.rule("error.msg.treasury.bank.gl.invalid",
                    "A bank account must use an enabled asset detail account");
        }
        return glAccount;
    }

    private Office office(Long officeId) {
        if (officeId == null) {
            return null;
        }
        return officeRepository.findOneWithNotFoundDetection(officeId);
    }
}
