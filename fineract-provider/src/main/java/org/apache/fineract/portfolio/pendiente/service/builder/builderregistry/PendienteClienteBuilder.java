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

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientRepositoryWrapper;
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
 * Single-step client follow-up. Stores {@code m_client.id} on the first step so the client page can list it.
 */
@Component
public class PendienteClienteBuilder implements PendingFlowBuilder {

    static final String BLUEPRINT_NAME = "pendiente_cliente";

    private final FromJsonHelper fromJsonHelper;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;
    private final ClientRepositoryWrapper clientRepositoryWrapper;

    public PendienteClienteBuilder(FromJsonHelper fromJsonHelper, OfficeRepositoryWrapper officeRepositoryWrapper,
            ClientRepositoryWrapper clientRepositoryWrapper) {
        this.fromJsonHelper = fromJsonHelper;
        this.officeRepositoryWrapper = officeRepositoryWrapper;
        this.clientRepositoryWrapper = clientRepositoryWrapper;
    }

    @Override
    public int getOrder() {
        return 100;
    }

    @Override
    public boolean supports(PendingFlowBlueprint blueprint) {
        return blueprint != null && BLUEPRINT_NAME.equals(blueprint.getName());
    }

    @Override
    public PendingFlowBuildResult build(PendingFlowBlueprint blueprint, PendingFlowBuildRequest request, PendingFlowBuildContext context) {
        Long clientId = request.getReferenceLong("clientId");
        if (clientId == null || clientId <= 0) {
            throw new IllegalArgumentException("clientId is required and must be positive");
        }
        Client client = clientRepositoryWrapper.findOneWithNotFoundDetection(clientId);

        AppUser responsable = context.getResponsableUser(request.getResponsableUserId());
        if (responsable == null) {
            throw new IllegalArgumentException("Responsable user not found: " + request.getResponsableUserId());
        }

        String clientName = StringUtils.defaultIfBlank(client.getDisplayName(), String.valueOf(clientId));
        String flowName = StringUtils.isNotBlank(request.getName()) ? request.getName() : "Pendiente - " + clientName;
        String note = StringUtils.trimToNull(request.getDescription());

        PendingFlow flow = PendingFlow.newInstance();
        flow.setName(flowName);
        flow.setDescription(note);
        flow.setCreator(context.getCurrentUser());
        flow.setCreationDate(context.getAuditDate());
        flow.setDueDate(request.getDueDate());
        flow.setStatus("active");
        flow.setPendingFlowBlueprint(blueprint);
        flow.setStepsId(null);
        flow.setLastCompletedStepId(null);

        String stepName = BLUEPRINT_NAME;
        String stepDescription = null;
        String stepsJson = blueprint.getSteps();
        if (StringUtils.isNotBlank(stepsJson)) {
            JsonArray stepsArray = fromJsonHelper.parse(stepsJson).getAsJsonArray();
            if (!stepsArray.isEmpty()) {
                JsonObject stepDef = stepsArray.get(0).getAsJsonObject();
                String definedName = fromJsonHelper.extractStringNamed("name", stepDef);
                if (StringUtils.isNotBlank(definedName)) {
                    stepName = definedName;
                }
                stepDescription = fromJsonHelper.extractStringNamed("description", stepDef);
            }
        }

        JsonObject refs = new JsonObject();
        JsonObject clientRef = new JsonObject();
        clientRef.addProperty("id", clientId);
        refs.add("m_client", clientRef);

        PendingStep firstStep = PendingStep.newInstance();
        firstStep.setName(stepName);
        firstStep.setDescription(stepDescription);
        firstStep.setStatus("open");
        firstStep.setNote(note);
        firstStep.setPendingFlow(flow);
        firstStep.setPreviousStep(null);
        firstStep.setCreator(context.getCurrentUser());
        firstStep.setCreationDate(context.getAuditDate());
        firstStep.setDueDate(request.getDueDate());
        firstStep.setResponsableUser(responsable);
        firstStep.setReferences(fromJsonHelper.toJson(refs));
        if (request.getOfficeId() != null) {
            Office office = officeRepositoryWrapper.findOneWithNotFoundDetection(request.getOfficeId());
            firstStep.setOffice(office);
        }

        return new PendingFlowBuildResult(flow, firstStep);
    }
}
