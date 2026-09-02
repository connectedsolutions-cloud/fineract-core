package org.apache.fineract.portfolio.invoice.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.client.domain.ClientChargePaidBy;
import org.apache.fineract.portfolio.client.domain.ClientTransaction;
import org.apache.fineract.portfolio.client.domain.ClientTransactionRepository;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;
import org.apache.fineract.portfolio.invoice.domain.MhDteAmountType;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponent;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponentRepository;
import org.apache.fineract.portfolio.invoice.domain.MhDteLoanComponent;
import org.apache.fineract.portfolio.loanaccount.domain.LoanChargePaidBy;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class InvoiceLineMhCategoryBuilderServiceImpl implements InvoiceLineMhCategoryBuilderService {

    private final LoanTransactionRepository loanTransactionRepository;
    private final ClientTransactionRepository clientTransactionRepository;
    private final MhDteItemComponentRepository mhDteItemComponentRepository;
    private final MhDteItemComponentRuleResolver ruleResolver;

    @Override
    @Transactional(readOnly = true)
    public List<InvoiceLineRequest> buildForLoanTransaction(Long loanTransactionId) {
        log.info("MH_DTE_BUILD_LINE_LOAN_START loanTransactionId={}", loanTransactionId);
        LoanTransaction txn = loanTransactionRepository.findByIdWithLoanAndChargesPaid(loanTransactionId).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.loan.transaction.not.found", "Loan transaction not found"));
        if (txn.isReversed()) {
            log.warn("MH_DTE_BUILD_LINE_LOAN_REVERSED loanTransactionId={} usingZeroLine=true", loanTransactionId);
            return List.of(defaultLine("LOAN_REVERSED", BigDecimal.ZERO));
        }
        String clientType = txn.getLoan() != null && txn.getLoan().getClient() != null && txn.getLoan().getClient().clientType() != null
                ? txn.getLoan().getClient().clientType().getLabel()
                : null;
        String clientKey = ruleResolver.normalizeClientTypeKey(clientType);
        List<MhDteItemComponent> mappings = mhDteItemComponentRepository.findAllByOrderByTargetUqAscClientTypeKeyAsc();

        List<ComponentSlice> slices = new ArrayList<>();
        BigDecimal principal = nullToZero(txn.getPrincipalPortion(txn.getLoan().getCurrency()).getAmount());
        slices.add(ComponentSlice.builder().source("LOAN.PRINCIPAL").targetUq(ruleResolver.targetUqLoan(MhDteLoanComponent.PRINCIPAL))
                .amount(principal).build());
        BigDecimal interest = nullToZero(txn.getInterestPortion(txn.getLoan().getCurrency()).getAmount());
        slices.add(ComponentSlice.builder().source("LOAN.INTEREST").targetUq(ruleResolver.targetUqLoan(MhDteLoanComponent.INTEREST))
                .amount(interest).build());
        for (LoanChargePaidBy paidBy : txn.getLoanChargesPaid()) {
            Long chargeId = paidBy.getLoanCharge().getCharge().getId();
            slices.add(ComponentSlice.builder().source("LOAN.CHARGE:" + chargeId).targetUq(ruleResolver.targetUqCharge(chargeId))
                    .amount(nullToZero(paidBy.getAmount())).build());
        }

        BigDecimal totalAmount = nullToZero(txn.getAmount(txn.getLoan().getCurrency()).getAmount()).abs();
        log.debug("MH_DTE_BUILD_LINE_LOAN_SLICES loanTransactionId={} clientKey={} componentCount={} totalAmount={}", loanTransactionId,
                clientKey, slices.size(), totalAmount);
        return List.of(buildSingleLine(slices, mappings, clientKey, "LOAN_TRANSACTION", loanTransactionId, totalAmount));
    }

    @Override
    @Transactional(readOnly = true)
    public List<InvoiceLineRequest> buildForClientTransaction(Long clientTransactionId) {
        log.info("MH_DTE_BUILD_LINE_CLIENT_START clientTransactionId={}", clientTransactionId);
        ClientTransaction txn = clientTransactionRepository.findById(clientTransactionId).orElseThrow(
                () -> new GeneralPlatformDomainRuleException("error.msg.client.transaction.not.found", "Client transaction not found"));
        if (txn.isReversed()) {
            log.warn("MH_DTE_BUILD_LINE_CLIENT_REVERSED clientTransactionId={} usingZeroLine=true", clientTransactionId);
            return List.of(defaultLine("CLIENT_REVERSED", BigDecimal.ZERO));
        }
        String clientType = txn.getClient() != null && txn.getClient().clientType() != null ? txn.getClient().clientType().getLabel()
                : null;
        String clientKey = ruleResolver.normalizeClientTypeKey(clientType);
        List<MhDteItemComponent> mappings = mhDteItemComponentRepository.findAllByOrderByTargetUqAscClientTypeKeyAsc();

        List<ComponentSlice> slices = new ArrayList<>();
        for (ClientChargePaidBy paidBy : txn.getClientChargePaidByCollection()) {
            Long chargeId = paidBy.getClientCharge().getCharge().getId();
            slices.add(ComponentSlice.builder().source("CLIENT.CHARGE:" + chargeId).targetUq(ruleResolver.targetUqCharge(chargeId))
                    .amount(nullToZero(paidBy.getAmount())).build());
        }

        BigDecimal totalAmount = nullToZero((BigDecimal) txn.toMapData().getOrDefault("amount", BigDecimal.ZERO)).abs();
        log.debug("MH_DTE_BUILD_LINE_CLIENT_SLICES clientTransactionId={} clientKey={} componentCount={} totalAmount={}",
                clientTransactionId, clientKey, slices.size(), totalAmount);
        return List.of(buildSingleLine(slices, mappings, clientKey, "CLIENT_TRANSACTION", clientTransactionId, totalAmount));
    }

    private InvoiceLineRequest buildSingleLine(List<ComponentSlice> slices, List<MhDteItemComponent> mappings, String clientKey,
            String transactionType, Long transactionId, BigDecimal totalAmount) {
        BigDecimal ventaNoSuj = BigDecimal.ZERO;
        BigDecimal ventaExenta = BigDecimal.ZERO;
        BigDecimal ventaGravada = BigDecimal.ZERO;
        BigDecimal noGravado = BigDecimal.ZERO;
        int unmappedCount = 0;
        List<Map<String, Object>> unmapped = new ArrayList<>();

        for (ComponentSlice slice : slices) {
            if (slice.getAmount().signum() <= 0) {
                continue;
            }
            MhDteItemComponent mapping = ruleResolver.pickMapping(mappings, slice.getTargetUq(), clientKey);
            if (mapping == null || mapping.getDteAmountType() == null) {
                unmappedCount++;
                unmapped.add(Map.of("source", slice.getSource(), "targetUq", slice.getTargetUq(), "amount", slice.getAmount()));
                continue;
            }
            MhDteAmountType type = mapping.getDteAmountType();
            switch (type) {
                case ventaNoSuj -> ventaNoSuj = ventaNoSuj.add(slice.getAmount());
                case ventaExenta -> ventaExenta = ventaExenta.add(slice.getAmount());
                case ventaGravada -> ventaGravada = ventaGravada.add(slice.getAmount());
                case noGravado, psv -> noGravado = noGravado.add(slice.getAmount());
                default -> {
                    unmappedCount++;
                    unmapped.add(Map.of("source", slice.getSource(), "targetUq", slice.getTargetUq(), "amount", slice.getAmount()));
                }
            }
        }

        if (unmappedCount > 0) {
            log.warn("MH_DTE_LINE_MAPPING_UNMAPPED transactionType={} transactionId={} clientKey={} unmappedCount={} details={}",
                    transactionType, transactionId, clientKey, unmappedCount, unmapped);
        } else {
            log.info("MH_DTE_LINE_MAPPING_OK transactionType={} transactionId={} clientKey={} mappedComponents={}", transactionType,
                    transactionId, clientKey, slices.size());
        }

        InvoiceLineRequest line = new InvoiceLineRequest();
        line.setNumItem(1);
        line.setTipoItem(1);
        line.setCantidad(BigDecimal.ONE);
        line.setUniMedida(99);
        line.setDescripcion(transactionType);
        line.setPrecioUni(totalAmount);
        line.setMontoDescu(BigDecimal.ZERO);
        line.setVentaNoSuj(ventaNoSuj);
        line.setVentaExenta(ventaExenta);
        line.setVentaGravada(ventaGravada);
        line.setTributos("[]");
        line.setNoGravado(noGravado);
        log.info(
                "MH_DTE_BUILD_LINE_RESULT transactionType={} transactionId={} totalAmount={} ventaNoSuj={} ventaExenta={} ventaGravada={} noGravado={} unmappedCount={}",
                transactionType, transactionId, totalAmount, ventaNoSuj, ventaExenta, ventaGravada, noGravado, unmappedCount);
        return line;
    }

    private static InvoiceLineRequest defaultLine(String description, BigDecimal totalAmount) {
        InvoiceLineRequest line = new InvoiceLineRequest();
        line.setNumItem(1);
        line.setTipoItem(1);
        line.setCantidad(BigDecimal.ONE);
        line.setUniMedida(99);
        line.setDescripcion(description);
        line.setPrecioUni(totalAmount);
        line.setMontoDescu(BigDecimal.ZERO);
        line.setVentaNoSuj(BigDecimal.ZERO);
        line.setVentaExenta(BigDecimal.ZERO);
        line.setVentaGravada(BigDecimal.ZERO);
        line.setTributos("[]");
        line.setNoGravado(BigDecimal.ZERO);
        return line;
    }

    private static BigDecimal nullToZero(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    @Getter
    @Builder
    private static class ComponentSlice {

        private final String source;
        private final String targetUq;
        private final BigDecimal amount;
    }
}
