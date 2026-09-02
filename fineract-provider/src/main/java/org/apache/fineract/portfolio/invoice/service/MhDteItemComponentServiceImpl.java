package org.apache.fineract.portfolio.invoice.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryRepository;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.portfolio.charge.domain.Charge;
import org.apache.fineract.portfolio.charge.domain.ChargeRepository;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentJournalLineData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentPreviewData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentPreviewLineData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentRequest;
import org.apache.fineract.portfolio.invoice.domain.MhDteAmountType;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponent;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponentRepository;
import org.apache.fineract.portfolio.invoice.domain.MhDteLoanComponent;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidBy;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class MhDteItemComponentServiceImpl implements MhDteItemComponentService {

    private final MhDteItemComponentRepository mhDteItemComponentRepository;
    private final ChargeRepository chargeRepository;
    private final LoanTransactionRepository loanTransactionRepository;
    private final JournalEntryRepository journalEntryRepository;
    private final PlatformSecurityContext platformSecurityContext;
    private final MhDteItemComponentRuleResolver ruleResolver;

    @Override
    @Transactional(readOnly = true)
    public List<MhDteItemComponentData> retrieveAll() {
        return mhDteItemComponentRepository.findAllByOrderByTargetUqAscClientTypeKeyAsc().stream().map(MhDteItemComponentData::from)
                .toList();
    }

    @Override
    @Transactional(readOnly = true)
    public MhDteItemComponentData retrieveOne(Long id) {
        MhDteItemComponent e = mhDteItemComponentRepository.findById(id).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.not.found", "Mapping not found"));
        return MhDteItemComponentData.from(e);
    }

    @Override
    @Transactional
    public MhDteItemComponentData create(MhDteItemComponentRequest request) {
        validateRequest(request);
        Charge charge = resolveCharge(request.getChargeId());
        MhDteLoanComponent loanComponent = parseLoanComponent(request.getLoanComponent());
        MhDteAmountType amountType = parseDteAmountType(request.getDteAmountType());
        String clientTypeKey = ruleResolver.normalizeClientTypeKey(request.getClientType());
        String targetUq = buildTargetUq(charge, loanComponent);
        MhDteItemComponent entity = MhDteItemComponent.create(request.getName(), amountType, charge, loanComponent,
                trimToNull(request.getClientType()), clientTypeKey, targetUq);
        applyAudit(entity, true);
        try {
            return MhDteItemComponentData.from(mhDteItemComponentRepository.saveAndFlush(entity));
        } catch (DataIntegrityViolationException ex) {
            throw new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.duplicate",
                    "A mapping with the same target and client type already exists", ex);
        }
    }

    @Override
    @Transactional
    public MhDteItemComponentData update(Long id, MhDteItemComponentRequest request) {
        validateRequest(request);
        MhDteItemComponent entity = mhDteItemComponentRepository.findById(id).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.not.found", "Mapping not found"));
        Charge charge = resolveCharge(request.getChargeId());
        MhDteLoanComponent loanComponent = parseLoanComponent(request.getLoanComponent());
        MhDteAmountType amountType = parseDteAmountType(request.getDteAmountType());
        String clientTypeKey = ruleResolver.normalizeClientTypeKey(request.getClientType());
        String targetUq = buildTargetUq(charge, loanComponent);
        entity.update(request.getName(), amountType, charge, loanComponent, trimToNull(request.getClientType()), clientTypeKey, targetUq);
        applyAudit(entity, false);
        try {
            return MhDteItemComponentData.from(mhDteItemComponentRepository.saveAndFlush(entity));
        } catch (DataIntegrityViolationException ex) {
            throw new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.duplicate",
                    "A mapping with the same target and client type already exists", ex);
        }
    }

    @Override
    @Transactional
    public void delete(Long id) {
        MhDteItemComponent entity = mhDteItemComponentRepository.findById(id).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.not.found", "Mapping not found"));
        mhDteItemComponentRepository.delete(entity);
    }

    @Override
    @Transactional(readOnly = true)
    public MhDteItemComponentPreviewData preview(Long loanTransactionId, String clientType, boolean includeJournalEntries) {
        LoanTransaction txn = loanTransactionRepository.findByIdWithLoanAndChargesPaid(loanTransactionId).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.loan.transaction.not.found", "Loan transaction not found"));
        if (txn.isReversed()) {
            throw new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.reversed.transaction",
                    "Cannot preview DTE mapping for a reversed loan transaction");
        }
        String requestedClientKey = ruleResolver.normalizeClientTypeKey(clientType);
        List<MhDteItemComponent> mappings = mhDteItemComponentRepository.findAllByOrderByTargetUqAscClientTypeKeyAsc();
        MonetaryCurrency currency = txn.getLoan().getCurrency();
        List<MhDteItemComponentPreviewLineData> lines = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        BigDecimal principal = nullToZero(txn.getPrincipalPortion(currency).getAmount());
        addComponentLine(lines, mappings, ruleResolver.targetUqLoan(MhDteLoanComponent.PRINCIPAL), requestedClientKey, "PRINCIPAL",
                principal, true);

        BigDecimal interest = nullToZero(txn.getInterestPortion(currency).getAmount());
        addComponentLine(lines, mappings, ruleResolver.targetUqLoan(MhDteLoanComponent.INTEREST), requestedClientKey, "INTEREST", interest,
                true);

        BigDecimal sumFeePaid = BigDecimal.ZERO;
        BigDecimal sumPenaltyPaid = BigDecimal.ZERO;
        for (LoanChargePaidBy pb : txn.getLoanChargesPaid()) {
            BigDecimal amt = nullToZero(pb.getAmount());
            if (pb.getLoanCharge().isPenaltyCharge()) {
                sumPenaltyPaid = sumPenaltyPaid.add(amt);
            } else {
                sumFeePaid = sumFeePaid.add(amt);
            }
            Long chargeDefId = pb.getLoanCharge().getCharge().getId();
            String source = "CHARGE:" + chargeDefId;
            addComponentLine(lines, mappings, ruleResolver.targetUqCharge(chargeDefId), requestedClientKey, source, amt, true);
        }

        BigDecimal feePortion = nullToZero(txn.getFeeChargesPortion(currency).getAmount());
        BigDecimal penaltyPortion = nullToZero(txn.getPenaltyChargesPortion(currency).getAmount());
        if (feePortion.subtract(sumFeePaid).abs().compareTo(new BigDecimal("0.0001")) > 0) {
            warnings.add("Fee portion on transaction differs from sum of charge-paid allocations by " + feePortion.subtract(sumFeePaid));
        }
        if (penaltyPortion.subtract(sumPenaltyPaid).abs().compareTo(new BigDecimal("0.0001")) > 0) {
            warnings.add("Penalty portion on transaction differs from sum of charge-paid allocations by "
                    + penaltyPortion.subtract(sumPenaltyPaid));
        }

        Map<String, BigDecimal> totals = new LinkedHashMap<>();
        for (MhDteItemComponentPreviewLineData line : lines) {
            String key = line.getDteAmountType() != null ? line.getDteAmountType() : "UNSET";
            totals.merge(key, line.getAmount(), BigDecimal::add);
        }

        List<MhDteItemComponentJournalLineData> journalLines = List.of();
        if (includeJournalEntries) {
            journalLines = journalEntryRepository.findByLoanTransactionIdAndReversedFalseOrderByIdAsc(loanTransactionId).stream()
                    .map(MhDteItemComponentServiceImpl::toJournalLine).toList();
        }

        return MhDteItemComponentPreviewData.builder().loanTransactionId(loanTransactionId).clientTypeInput(clientType).lines(lines)
                .totalsByDteAmountType(totals).warnings(warnings).journalEntries(journalLines).build();
    }

    private static MhDteItemComponentJournalLineData toJournalLine(JournalEntry je) {
        return MhDteItemComponentJournalLineData.builder().id(je.getId()).glAccountId(je.getGlAccount().getId()).amount(je.getAmount())
                .debit(je.isDebitEntry()).entryDate(je.getTransactionDate()).description(je.getDescription()).build();
    }

    private void addComponentLine(List<MhDteItemComponentPreviewLineData> lines, List<MhDteItemComponent> mappings, String targetUq,
            String requestedClientKey, String source, BigDecimal amount, boolean requireMappingWhenPositive) {
        if (amount.signum() <= 0) {
            return;
        }
        MhDteItemComponent mapping = ruleResolver.pickMapping(mappings, targetUq, requestedClientKey);
        if (mapping == null) {
            if (requireMappingWhenPositive) {
                throw new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.mapping.missing",
                        "No MH DTE item mapping for target " + targetUq + " and client type key " + requestedClientKey);
            }
            return;
        }
        lines.add(MhDteItemComponentPreviewLineData.builder().mappingId(mapping.getId()).mappingName(mapping.getName())
                .dteAmountType(mapping.getDteAmountType() != null ? mapping.getDteAmountType().name() : null).source(source).amount(amount)
                .matchedClientTypeKey(mapping.getClientTypeKey()).build());
    }

    private void validateRequest(MhDteItemComponentRequest request) {
        if (request.getName() == null || request.getName().isBlank()) {
            throw new GeneralPlatformDomainRuleException("validation.msg.mh.dte.item.component.name.required", "name is required");
        }
    }

    private static MhDteAmountType parseDteAmountType(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        return MhDteAmountType.fromApi(raw);
    }

    private Charge resolveCharge(Long chargeId) {
        if (chargeId == null) {
            return null;
        }
        return chargeRepository.findById(chargeId)
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.charge.id.invalid", "Charge not found: " + chargeId));
    }

    private static MhDteLoanComponent parseLoanComponent(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        return MhDteLoanComponent.fromApi(raw);
    }

    private static String buildTargetUq(Charge charge, MhDteLoanComponent loanComponent) {
        if (charge != null) {
            return "C_" + charge.getId();
        }
        if (loanComponent != null) {
            return "L_" + loanComponent.name();
        }
        return "P_" + UUID.randomUUID().toString().replace("-", "");
    }

    private static String trimToNull(String s) {
        if (s == null) {
            return null;
        }
        String t = s.trim();
        return t.isEmpty() ? null : t;
    }

    private static BigDecimal nullToZero(BigDecimal v) {
        return v == null ? BigDecimal.ZERO : v;
    }

    private void applyAudit(MhDteItemComponent entity, boolean isNew) {
        Long userId = platformSecurityContext.getAuthenticatedUserIfPresent().getId();
        var now = DateUtils.getLocalDateTimeOfTenant();
        if (isNew) {
            entity.setCreatedBy(userId);
            entity.setCreatedDate(now);
        }
        entity.setLastModifiedBy(userId);
        entity.setLastModifiedDate(now);
    }
}
