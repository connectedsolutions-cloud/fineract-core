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
package org.apache.fineract.portfolio.pendiente.service;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowData;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprintRepository;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowRepository;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.domain.PendingStepRepository;
import org.apache.fineract.portfolio.pendiente.exception.PendingFlowBlueprintNotFoundException;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildContext;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildRequest;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuildResult;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilderRegistry;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class PendingFlowWritePlatformServiceImpl implements PendingFlowWritePlatformService {

    private static final Set<String> RESERVED_KEYS = Set.of("blueprintId", "responsableUserId", "dueDate", "name",
            "description", "assignees", "officeId");

    private final PendingFlowRepository flowRepository;
    private final PendingFlowBlueprintRepository blueprintRepository;
    private final PendingStepRepository stepRepository;
    private final AppUserRepository appUserRepository;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;
    private final PlatformSecurityContext context;
    private final FromJsonHelper fromJsonHelper;
    private final PendingFlowReadPlatformService readService;
    private final PendingFlowBuilderRegistry builderRegistry;

    @Transactional
    @Override
    public PendingFlowData createFromBlueprint(Long blueprintId, String json) {
        AppUser currentUser = context.authenticatedUser();
        PendingFlowBlueprint blueprint = blueprintRepository.findById(blueprintId)
                .orElseThrow(() -> new PendingFlowBlueprintNotFoundException(blueprintId));

        JsonObject request = StringUtils.isNotBlank(json) ? fromJsonHelper.parse(json).getAsJsonObject() : new JsonObject();
        String name = request.has("name") ? fromJsonHelper.extractStringNamed("name", request) : null;
        if (StringUtils.isBlank(name)) {
            name = blueprint.getName() + " - " + DateUtils.getAuditOffsetDateTime().toString();
        }
        String description = request.has("description") ? fromJsonHelper.extractStringNamed("description", request) : null;
        JsonArray assigneesArray = request.has("assignees") ? fromJsonHelper.extractJsonArrayNamed("assignees", request) : null;
        Long officeId = request.has("officeId") ? fromJsonHelper.extractLongNamed("officeId", request) : null;
        Office office = officeId != null ? officeRepositoryWrapper.findOneWithNotFoundDetection(officeId) : null;

        PendingFlow flow = PendingFlow.newInstance();
        flow.setName(name);
        flow.setDescription(description);
        flow.setCreator(currentUser);
        flow.setCreationDate(DateUtils.getAuditOffsetDateTime());
        flow.setDueDate(null);
        flow.setStatus("active");
        flow.setPendingFlowBlueprint(blueprint);
        flow.setStepsId(null);
        flow.setLastCompletedStepId(null);
        flow = flowRepository.saveAndFlush(flow);

        String stepsJson = blueprint.getSteps();
        List<Long> stepIds = new ArrayList<>();
        if (StringUtils.isNotBlank(stepsJson)) {
            JsonArray stepsArray = fromJsonHelper.parse(stepsJson).getAsJsonArray();
            PendingStep previous = null;
            for (int i = 0; i < stepsArray.size(); i++) {
                JsonObject stepDef = stepsArray.get(i).getAsJsonObject();
                String stepName = fromJsonHelper.extractStringNamed("name", stepDef);
                String stepDesc = fromJsonHelper.extractStringNamed("description", stepDef);
                String stepReferences = stepDef.has("reference_fields")
                        ? fromJsonHelper.toJson(stepDef.get("reference_fields")) : null;

                Long responsableId = resolveResponsableForOrder(i, assigneesArray, currentUser.getId());
                AppUser responsable = responsableId != null ? appUserRepository.findById(responsableId).orElse(null) : null;
                if (responsable == null) {
                    responsable = currentUser;
                }

                PendingStep step = PendingStep.newInstance();
                step.setName(stepName);
                step.setDescription(stepDesc);
                step.setStatus(i == 0 ? "open" : "blocked");
                step.setNote(null);
                step.setPendingFlow(flow);
                step.setPreviousStep(previous);
                step.setCreator(currentUser);
                step.setCreationDate(DateUtils.getAuditOffsetDateTime());
                step.setDueDate(null);
                step.setResponsableUser(responsable);
                step.setReferences(stepReferences);
                if (office != null) {
                    step.setOffice(office);
                }
                step = stepRepository.saveAndFlush(step);
                stepIds.add(step.getId());
                previous = step;
            }
        }

        flow.setStepsId(fromJsonHelper.toJson(stepIds));
        flowRepository.saveAndFlush(flow);

        return readService.retrieveOne(flow.getId(), true);
    }

    @Transactional
    @Override
    public PendingFlowData createFlowAndFirstStep(Long blueprintId, String json) {
        if (StringUtils.isBlank(json)) {
            throw new IllegalArgumentException("Request body is required");
        }
        JsonObject request = fromJsonHelper.parse(json).getAsJsonObject();
        Long responsableUserId = fromJsonHelper.extractLongNamed("responsableUserId", request);
        if (responsableUserId == null) {
            throw new IllegalArgumentException("responsableUserId is required");
        }
        AppUser responsable = appUserRepository.findById(responsableUserId).orElse(null);
        if (responsable == null) {
            throw new IllegalArgumentException("Responsable user not found: " + responsableUserId);
        }

        OffsetDateTime dueDate = null;
        if (request.has("dueDate") && !request.get("dueDate").isJsonNull()) {
            String dueDateStr = fromJsonHelper.extractStringNamed("dueDate", request);
            if (StringUtils.isNotBlank(dueDateStr)) {
                try {
                    dueDate = OffsetDateTime.parse(dueDateStr);
                } catch (Exception e) {
                    throw new IllegalArgumentException("Invalid dueDate format: " + dueDateStr);
                }
            }
        }

        String name = request.has("name") ? fromJsonHelper.extractStringNamed("name", request) : null;
        String description = request.has("description") ? fromJsonHelper.extractStringNamed("description", request) : null;
        Long officeId = request.has("officeId") ? fromJsonHelper.extractLongNamed("officeId", request) : null;

        Map<String, Object> references = new HashMap<>();
        for (String key : request.keySet()) {
            if (!RESERVED_KEYS.contains(key)) {
                JsonElement el = request.get(key);
                if (el != null && !el.isJsonNull()) {
                    if (el.isJsonPrimitive()) {
                        if (el.getAsJsonPrimitive().isNumber()) {
                            references.put(key, el.getAsJsonPrimitive().getAsNumber().longValue());
                        } else if (el.getAsJsonPrimitive().isBoolean()) {
                            references.put(key, el.getAsBoolean());
                        } else {
                            references.put(key, el.getAsString());
                        }
                    } else {
                        references.put(key, fromJsonHelper.toJson(el));
                    }
                }
            }
        }

        PendingFlowBlueprint blueprint = blueprintRepository.findById(blueprintId)
                .orElseThrow(() -> new PendingFlowBlueprintNotFoundException(blueprintId));

        PendingFlowBuildRequest buildRequest = PendingFlowBuildRequest.builder().responsableUserId(responsableUserId)
                .dueDate(dueDate).name(name).description(description).officeId(officeId).references(references).build();

        PendingFlowBuildContext buildContext = new PendingFlowBuildContext(context.authenticatedUser(),
                DateUtils.getAuditOffsetDateTime(), appUserRepository);

        PendingFlowBuildResult result = builderRegistry.getBuilder(blueprint).build(blueprint, buildRequest, buildContext);

        PendingFlow flow = result.getFlow();
        PendingStep firstStep = result.getFirstStep();
        flow.setPendingFlowBlueprint(blueprint); // Ensure pending_flow_blueprint_id is always persisted
        flow = flowRepository.saveAndFlush(flow);
        firstStep.setPendingFlow(flow);
        firstStep = stepRepository.saveAndFlush(firstStep);
        flow.setStepsId(fromJsonHelper.toJson(List.of(firstStep.getId())));
        flowRepository.saveAndFlush(flow);

        return readService.retrieveOne(flow.getId(), true);
    }

    private Long resolveResponsableForOrder(int order, JsonArray assigneesArray, Long defaultUserId) {
        if (assigneesArray == null) {
            return defaultUserId;
        }
        for (JsonElement el : assigneesArray) {
            JsonObject o = el.getAsJsonObject();
            if (o.has("order") && o.get("order").getAsInt() == order && o.has("userId")) {
                return o.get("userId").getAsLong();
            }
        }
        return defaultUserId;
    }
}
