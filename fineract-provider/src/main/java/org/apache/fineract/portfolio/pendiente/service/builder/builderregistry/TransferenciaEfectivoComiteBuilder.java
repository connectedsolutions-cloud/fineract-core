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
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.comite.domain.SesionComiteRepository;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildContext;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildRequest;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildResult;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilder;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.stereotype.Component;

/**
 * Builder for the transferencia_efectivo-comite_otrgamiento blueprint. Loads SesionComite by
 * sesionComiteId from the request and builds the first step's references JSON.
 */
@Component
public class TransferenciaEfectivoComiteBuilder implements PendingFlowBuilder {

    private static final String BLUEPRINT_NAME = "transferencia_efectivo-comite_otrgamiento";

    private final SesionComiteRepository sesionComiteRepository;
    private final FromJsonHelper fromJsonHelper;

    public TransferenciaEfectivoComiteBuilder(SesionComiteRepository sesionComiteRepository,
            FromJsonHelper fromJsonHelper) {
        this.sesionComiteRepository = sesionComiteRepository;
        this.fromJsonHelper = fromJsonHelper;
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
