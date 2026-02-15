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

import com.google.gson.JsonObject;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.accounting.accountingOperations.AvailableAtCashierAccountingHelper;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.comite.domain.SesionComiteRepository;
import org.apache.fineract.portfolio.comite.service.SesionComiteReadPlatformService;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.service.LoanAssembler;
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
 * Builder for the transferencia_efectivo-comite_otrgamiento blueprint. Loads SesionComite by
 * sesionComiteId from the request and builds the first step's references JSON.
 */
@Component
public class TransferenciaEfectivoComiteBuilder implements PendingFlowBuilder {

    private static final Logger log = LoggerFactory.getLogger(TransferenciaEfectivoComiteBuilder.class);
    private static final String BLUEPRINT_NAME = "transferencia_efectivo-comite_otrgamiento";
    private static final String STEP_NAME_VAULT_RECEPTION = "transferencia_cheque_boveda";
    private static final String STEP_NAME_RECEPCION_CAJA_CIERRE = "recepcion_caja_cierre_cuentas_por_cobrar";

    private record AtCashierStepContext(SesionComite session, List<Loan> processedLoans, LocalDate businessDate) {}

    private final SesionComiteRepository sesionComiteRepository;
    private final FromJsonHelper fromJsonHelper;
    private final AvailableAtCashierAccountingHelper availableAtCashierAccountingHelper;
    private final SesionComiteReadPlatformService sesionComiteReadPlatformService;
    private final LoanAssembler loanAssembler;

    public TransferenciaEfectivoComiteBuilder(SesionComiteRepository sesionComiteRepository,
            FromJsonHelper fromJsonHelper,
            AvailableAtCashierAccountingHelper availableAtCashierAccountingHelper,
            SesionComiteReadPlatformService sesionComiteReadPlatformService,
            LoanAssembler loanAssembler) {
        this.sesionComiteRepository = sesionComiteRepository;
        this.fromJsonHelper = fromJsonHelper;
        this.availableAtCashierAccountingHelper = availableAtCashierAccountingHelper;
        this.sesionComiteReadPlatformService = sesionComiteReadPlatformService;
        this.loanAssembler = loanAssembler;
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
    public PendingFlowBuildResult build(PendingFlowBlueprint blueprint, PendingFlowBuildRequest request,
            PendingFlowBuildContext context) {
        AppUser responsable = context.getResponsableUser(request.getResponsableUserId());
        if (responsable == null) {
            throw new IllegalArgumentException("Responsable user not found: " + request.getResponsableUserId());
        }

        Long sesionComiteId = request.getReferenceLong("sesionComiteId");
        if (sesionComiteId == null || sesionComiteId <= 0) {
            throw new IllegalArgumentException("sesionComiteId is required and must be positive");
        }

        SesionComite sesionComite = sesionComiteRepository.findById(sesionComiteId).orElseThrow(
                () -> new IllegalArgumentException("SesionComite not found: " + sesionComiteId));

        String referencesJson = buildReferencesJson(sesionComite);

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
        String stepName = "transferencia_cheque_boveda";
        String stepDescription = "cambio de cheque de banco y recepción en boveda";
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

        return new PendingFlowBuildResult(flow, firstStep);
    }

    @Override
    public void onStepCompleted(PendingFlow flow, PendingStep completedStep, PendingStep nextStepOrNull) {
        if (completedStep == null) {
            return;
        }
        String stepName = completedStep.getName();
        if (!STEP_NAME_VAULT_RECEPTION.equals(stepName) && !STEP_NAME_RECEPCION_CAJA_CIERRE.equals(stepName)) {
            return;
        }
        AtCashierStepContext ctx = resolveAtCashierStepContext(completedStep);
        if (ctx == null) {
            return;
        }
        if (STEP_NAME_VAULT_RECEPTION.equals(stepName)) {
            availableAtCashierAccountingHelper.vaultReceptionFromBank(ctx.session(), ctx.processedLoans(), ctx.businessDate());
        } else if (STEP_NAME_RECEPCION_CAJA_CIERRE.equals(stepName)) {
            availableAtCashierAccountingHelper.cashierCashReception(ctx.session(), ctx.processedLoans(), ctx.businessDate());
            availableAtCashierAccountingHelper.disbursementPayableClearing(ctx.session(), ctx.processedLoans(), ctx.businessDate());
        }
    }

    /**
     * Resolves session, processed loans, and business date from the completed step's references.
     * Returns null if references are invalid, session not found, or office missing (logs as needed).
     */
    private AtCashierStepContext resolveAtCashierStepContext(PendingStep completedStep) {
        Long sessionId = parseSessionIdFromReferences(completedStep.getReferences());
        if (sessionId == null || sessionId <= 0) {
            log.debug("TransferenciaEfectivoComiteBuilder: missing or invalid m_sesiones_comite.id in step references, skipping at-cashier accounting");
            return null;
        }
        SesionComite session = sesionComiteRepository.findById(sessionId).orElse(null);
        if (session == null) {
            log.warn("TransferenciaEfectivoComiteBuilder: SesionComite not found for id {}, skipping at-cashier accounting", sessionId);
            return null;
        }
        Long officeId = session.getOffice() != null ? session.getOffice().getId() : null;
        if (officeId == null) {
            log.warn("TransferenciaEfectivoComiteBuilder: session {} has no office, skipping at-cashier accounting", sessionId);
            return null;
        }
        List<Long> approvedLoanIds = sesionComiteReadPlatformService.retrieveApprovedLoanIds(sessionId, officeId);
        List<Loan> processedLoans = new ArrayList<>();
        for (Long loanId : approvedLoanIds) {
            try {
                Loan loan = loanAssembler.assembleFrom(loanId);
                if (loan != null) {
                    processedLoans.add(loan);
                }
            } catch (Exception e) {
                log.debug("TransferenciaEfectivoComiteBuilder: could not assemble loan {} for session {}, skipping", loanId, sessionId, e);
            }
        }
        LocalDate businessDate = DateUtils.getBusinessLocalDate();
        return new AtCashierStepContext(session, processedLoans, businessDate);
    }

    /**
     * Parses the comite-session id from step references JSON (shape: {"m_sesiones_comite":{"id":...}}).
     * Returns null if references are null/blank or the path is missing/invalid.
     */
    private Long parseSessionIdFromReferences(String references) {
        if (StringUtils.isBlank(references)) {
            return null;
        }
        try {
            JsonObject root = fromJsonHelper.parse(references).getAsJsonObject();
            if (root == null || !root.has("m_sesiones_comite")) {
                return null;
            }
            JsonObject sesion = root.getAsJsonObject("m_sesiones_comite");
            return fromJsonHelper.extractLongNamed("id", sesion);
        } catch (Exception e) {
            log.debug("TransferenciaEfectivoComiteBuilder.parseSessionIdFromReferences: failed to parse references", e);
            return null;
        }
    }

    private String buildReferencesJson(SesionComite sesionComite) {
        JsonObject refs = new JsonObject();
        JsonObject sesion = new JsonObject();
        sesion.addProperty("id", sesionComite.getId());
        if (sesionComite.getSelection() != null) {
            sesion.addProperty("selection", sesionComite.getSelection());
        }
        if (sesionComite.getIntegrantes() != null) {
            sesion.addProperty("integrantes", sesionComite.getIntegrantes());
        }
        refs.add("m_sesiones_comite", sesion);
        return fromJsonHelper.toJson(refs);
    }
}
