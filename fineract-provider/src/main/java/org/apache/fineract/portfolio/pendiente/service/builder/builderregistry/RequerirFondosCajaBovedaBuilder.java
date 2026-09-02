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
package org.apache.fineract.portfolio.pendiente.service.builder.builderregistry;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.math.BigDecimal;
import java.time.LocalDate;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.accounting.accountingOperations.TellerVaultTransferAccountingHelper;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.teller.domain.Cashier;
import org.apache.fineract.organisation.teller.domain.CashierRepository;
import org.apache.fineract.organisation.teller.domain.CashierTransaction;
import org.apache.fineract.organisation.teller.domain.CashierTransactionRepository;
import org.apache.fineract.organisation.teller.domain.CashierTxnType;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildContext;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildRequest;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildResult;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilder;
import org.apache.fineract.useradministration.domain.AppUser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Builder for requerir-fondos-caja-boveda: cashier requests funds from vault; approver completes step requerir-fondos.
 * On completion, ALLOCATE cashier txn and GL (debit cash-at-teller, credit main vault).
 */
@Component
public class RequerirFondosCajaBovedaBuilder implements PendingFlowBuilder {

    private static final Logger log = LoggerFactory.getLogger(RequerirFondosCajaBovedaBuilder.class);
    private static final String BLUEPRINT_NAME = "requerir-fondos-caja-boveda";
    private static final String STEP_NAME_REQUERIR_FONDOS = "requerir-fondos";

    private final CashierRepository cashierRepository;
    private final CashierTransactionRepository cashierTransactionRepository;
    private final FromJsonHelper fromJsonHelper;
    private final TellerVaultTransferAccountingHelper tellerVaultTransferAccountingHelper;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;

    public RequerirFondosCajaBovedaBuilder(CashierRepository cashierRepository, CashierTransactionRepository cashierTransactionRepository,
            FromJsonHelper fromJsonHelper, TellerVaultTransferAccountingHelper tellerVaultTransferAccountingHelper,
            OfficeRepositoryWrapper officeRepositoryWrapper) {
        this.cashierRepository = cashierRepository;
        this.cashierTransactionRepository = cashierTransactionRepository;
        this.fromJsonHelper = fromJsonHelper;
        this.tellerVaultTransferAccountingHelper = tellerVaultTransferAccountingHelper;
        this.officeRepositoryWrapper = officeRepositoryWrapper;
    }

    @Override
    public int getOrder() {
        return 0;
    }

    @Override
    public boolean supports(PendingFlowBlueprint blueprint) {
        return BLUEPRINT_NAME.equals(blueprint.getName());
    }

    @Override
    public PendingFlowBuildResult build(PendingFlowBlueprint blueprint, PendingFlowBuildRequest request, PendingFlowBuildContext context) {
        AppUser responsable = context.getResponsableUser(request.getResponsableUserId());
        if (responsable == null) {
            throw new IllegalArgumentException("Responsable user not found: " + request.getResponsableUserId());
        }

        Long cashierId = request.getReferenceLong("cashierId");
        if (cashierId == null || cashierId <= 0) {
            throw new IllegalArgumentException("cashierId is required and must be positive");
        }

        Cashier cashier = cashierRepository.findById(cashierId)
                .orElseThrow(() -> new IllegalArgumentException("Cashier not found: " + cashierId));

        BigDecimal amount = parseAmount(request.getReference("amount"));
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("amount is required and must be positive (send as string e.g. \"1000.00\")");
        }

        String currencyCode = parseStringReference(request.getReference("currencyCode"));
        if (StringUtils.isBlank(currencyCode)) {
            throw new IllegalArgumentException("currencyCode is required");
        }

        Office office = cashier.getTeller() != null ? cashier.getTeller().getOffice() : null;
        if (office == null && request.getOfficeId() != null) {
            office = officeRepositoryWrapper.findOneWithNotFoundDetection(request.getOfficeId());
        }
        if (office == null) {
            throw new IllegalArgumentException("Cashier has no teller/office and officeId was not provided");
        }

        String referencesJson = buildReferencesJson(cashierId, request.getResponsableUserId(), amount.toPlainString(), currencyCode);

        String flowName = StringUtils.isNotBlank(request.getName()) ? request.getName()
                : blueprint.getName() + " - " + context.getAuditDate();

        PendingFlow flow = PendingFlow.newInstance();
        flow.setName(flowName);
        flow.setDescription(request.getDescription());
        flow.setCreator(context.getCurrentUser());
        flow.setCreationDate(context.getAuditDate());
        flow.setDueDate(request.getDueDate());
        flow.setStatus("active");
        flow.setPendingFlowBlueprint(blueprint);
        flow.setStepsId(null);
        flow.setLastCompletedStepId(null);

        String stepsJson = blueprint.getSteps();
        String stepName = STEP_NAME_REQUERIR_FONDOS;
        String stepDescription = "Approve vault-to-cashier allocation";
        if (StringUtils.isNotBlank(stepsJson)) {
            var stepsArray = fromJsonHelper.parse(stepsJson).getAsJsonArray();
            if (!stepsArray.isEmpty()) {
                var stepDef = stepsArray.get(0).getAsJsonObject();
                stepName = fromJsonHelper.extractStringNamed("name", stepDef);
                stepDescription = fromJsonHelper.extractStringNamed("description", stepDef);
            }
        }

        PendingStep firstStep = PendingStep.newInstance();
        firstStep.setName(stepName);
        firstStep.setDescription(stepDescription);
        firstStep.setStatus("open");
        firstStep.setNote(null);
        firstStep.setPendingFlow(flow);
        firstStep.setPreviousStep(null);
        firstStep.setCreator(context.getCurrentUser());
        firstStep.setCreationDate(context.getAuditDate());
        firstStep.setDueDate(request.getDueDate());
        firstStep.setResponsableUser(responsable);
        firstStep.setReferences(referencesJson);
        firstStep.setOffice(office);

        return new PendingFlowBuildResult(flow, firstStep);
    }

    @Override
    public void onStepCompleted(PendingFlow flow, PendingStep completedStep, PendingStep nextStepOrNull) {
        if (completedStep == null) {
            return;
        }
        if (!STEP_NAME_REQUERIR_FONDOS.equals(completedStep.getName())) {
            return;
        }
        if (nextStepOrNull != null) {
            return;
        }
        Long cashierId = parseLongFromReferences(completedStep.getReferences(), "cashierId");
        BigDecimal amount = parseAmountFromReferences(completedStep.getReferences());
        String currencyCode = parseStringFromReferences(completedStep.getReferences(), "currencyCode");
        if (cashierId == null || amount == null || amount.compareTo(BigDecimal.ZERO) <= 0 || StringUtils.isBlank(currencyCode)) {
            log.warn(
                    "RequerirFondosCajaBovedaBuilder: missing or invalid references (cashierId, amount, currencyCode), skipping allocation");
            return;
        }
        Cashier cashier = cashierRepository.findById(cashierId).orElse(null);
        if (cashier == null) {
            log.warn("RequerirFondosCajaBovedaBuilder: Cashier not found for id {}, skipping allocation", cashierId);
            return;
        }
        Office office = cashier.getTeller() != null ? cashier.getTeller().getOffice() : null;
        if (office == null) {
            log.warn("RequerirFondosCajaBovedaBuilder: Cashier {} has no teller/office, skipping allocation", cashierId);
            return;
        }
        LocalDate businessDate = DateUtils.getBusinessLocalDate();
        String description = "Pending flow requerir-fondos-caja-boveda approval";

        CashierTransaction cashierTxn = CashierTransaction.createBalanceTransaction(cashier, CashierTxnType.ALLOCATE.getId(), amount,
                businessDate, currencyCode, description);
        cashierTransactionRepository.save(cashierTxn);

        String transactionId = TellerVaultTransferAccountingHelper.generateRequestVaultTransactionId(flow != null ? flow.getId() : null,
                completedStep.getId());
        tellerVaultTransferAccountingHelper.postVaultTransferToTeller(office, amount, currencyCode, businessDate, transactionId,
                description);
    }

    private static BigDecimal parseAmount(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof BigDecimal) {
            return (BigDecimal) value;
        }
        if (value instanceof Number) {
            return BigDecimal.valueOf(((Number) value).doubleValue());
        }
        if (value instanceof String) {
            String s = ((String) value).trim();
            if (s.isEmpty()) {
                return null;
            }
            try {
                return new BigDecimal(s);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    private static String parseStringReference(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof String) {
            return (String) value;
        }
        return value.toString();
    }

    private String buildReferencesJson(Long cashierId, Long responsableUserId, String amount, String currencyCode) {
        JsonObject refs = new JsonObject();
        refs.addProperty("cashierId", cashierId);
        refs.addProperty("responsable_user", responsableUserId);
        refs.addProperty("amount", amount);
        refs.addProperty("currencyCode", currencyCode);
        return fromJsonHelper.toJson(refs);
    }

    private Long parseLongFromReferences(String references, String key) {
        if (StringUtils.isBlank(references)) {
            return null;
        }
        try {
            JsonObject root = fromJsonHelper.parse(references).getAsJsonObject();
            if (root == null || !root.has(key)) {
                return null;
            }
            return fromJsonHelper.extractLongNamed(key, root);
        } catch (Exception e) {
            log.debug("RequerirFondosCajaBovedaBuilder.parseLongFromReferences: failed to parse {} from references", key, e);
            return null;
        }
    }

    private String parseStringFromReferences(String references, String key) {
        if (StringUtils.isBlank(references)) {
            return null;
        }
        try {
            JsonObject root = fromJsonHelper.parse(references).getAsJsonObject();
            if (root == null || !root.has(key)) {
                return null;
            }
            return fromJsonHelper.extractStringNamed(key, root);
        } catch (Exception e) {
            log.debug("RequerirFondosCajaBovedaBuilder.parseStringFromReferences: failed to parse {} from references", key, e);
            return null;
        }
    }

    private BigDecimal parseAmountFromReferences(String references) {
        if (StringUtils.isBlank(references)) {
            return null;
        }
        try {
            JsonObject root = fromJsonHelper.parse(references).getAsJsonObject();
            if (root == null || !root.has("amount")) {
                return null;
            }
            JsonElement amt = root.get("amount");
            if (amt == null || amt.isJsonNull()) {
                return null;
            }
            if (amt.isJsonPrimitive()) {
                if (amt.getAsJsonPrimitive().isNumber()) {
                    return amt.getAsBigDecimal();
                }
                if (amt.getAsJsonPrimitive().isString()) {
                    return new BigDecimal(amt.getAsString());
                }
            }
            return null;
        } catch (Exception e) {
            log.debug("RequerirFondosCajaBovedaBuilder.parseAmountFromReferences: failed to parse amount", e);
            return null;
        }
    }
}
