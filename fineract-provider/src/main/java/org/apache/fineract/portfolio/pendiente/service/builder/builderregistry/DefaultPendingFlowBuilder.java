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
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildContext;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildRequest;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildResult;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilder;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.core.Ordered;
import org.springframework.stereotype.Component;

/**
 * Fallback builder that supports any blueprint. Creates the first step with passthrough
 * references (copy of blueprint reference_fields). Responsable user and due date come from
 * the request.
 */
@Component
public class DefaultPendingFlowBuilder implements PendingFlowBuilder {

    private final FromJsonHelper fromJsonHelper;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;

    public DefaultPendingFlowBuilder(FromJsonHelper fromJsonHelper, OfficeRepositoryWrapper officeRepositoryWrapper) {
        this.fromJsonHelper = fromJsonHelper;
        this.officeRepositoryWrapper = officeRepositoryWrapper;
    }

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public boolean supports(PendingFlowBlueprint blueprint) {
        return true;
    }

    @Override
    public PendingFlowBuildResult build(PendingFlowBlueprint blueprint, PendingFlowBuildRequest request,
            PendingFlowBuildContext context) {
        AppUser responsable = context.getResponsableUser(request.getResponsableUserId());
        if (responsable == null) {
            throw new IllegalArgumentException("Responsable user not found: " + request.getResponsableUserId());
        }

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
        String stepName = "Step 1";
        String stepDescription = null;
        String stepReferences = null;
        if (StringUtils.isNotBlank(stepsJson)) {
            JsonArray stepsArray = fromJsonHelper.parse(stepsJson).getAsJsonArray();
            if (!stepsArray.isEmpty()) {
                JsonObject stepDef = stepsArray.get(0).getAsJsonObject();
                stepName = fromJsonHelper.extractStringNamed("name", stepDef);
                stepDescription = fromJsonHelper.extractStringNamed("description", stepDef);
                if (stepDef.has("reference_fields")) {
                    stepReferences = fromJsonHelper.toJson(stepDef.get("reference_fields"));
                }
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
        firstStep.setReferences(stepReferences);
        if (request.getOfficeId() != null) {
            Office office = officeRepositoryWrapper.findOneWithNotFoundDetection(request.getOfficeId());
            firstStep.setOffice(office);
        }

        return new PendingFlowBuildResult(flow, firstStep);
    }
}
