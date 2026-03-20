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
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.portfolio.pendiente.data.PendingStepData;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowRepository;
import org.apache.fineract.portfolio.pendiente.domain.PendingStepRepository;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilder;
import org.apache.fineract.portfolio.pendiente.service.builder.PendingFlowBuilderRegistry;
import org.apache.fineract.portfolio.pendiente.exception.PendingStepNotFoundException;
import org.apache.fineract.useradministration.domain.AppUser;
import org.apache.fineract.useradministration.domain.AppUserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class PendingStepWritePlatformServiceImpl implements PendingStepWritePlatformService {

    private final PendingStepRepository stepRepository;
    private final PendingFlowRepository flowRepository;
    private final AppUserRepository appUserRepository;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;
    private final PlatformSecurityContext context;
    private final FromJsonHelper fromJsonHelper;
    private final PendingStepReadPlatformService readService;
    private final PendingFlowBuilderRegistry builderRegistry;

    @Transactional
    @Override
    public PendingStepData update(Long id, String json) {
        context.authenticatedUser();
        PendingStep step = stepRepository.findById(id).orElseThrow(() -> new PendingStepNotFoundException(id));
        if (json != null && !json.isBlank()) {
            var object = fromJsonHelper.parse(json).getAsJsonObject();
            if (object.has("status")) {
                step.setStatus(fromJsonHelper.extractStringNamed("status", object));
            }
            if (object.has("note")) {
                step.setNote(fromJsonHelper.extractStringNamed("note", object));
            }
            if (object.has("description")) {
                step.setDescription(fromJsonHelper.extractStringNamed("description", object));
            }
            if (object.has("officeId")) {
                Long officeId = fromJsonHelper.extractLongNamed("officeId", object);
                if (officeId != null) {
                    Office office = officeRepositoryWrapper.findOneWithNotFoundDetection(officeId);
                    step.setOffice(office);
                } else {
                    step.setOffice(null);
                }
            }
            step = stepRepository.saveAndFlush(step);
        }
        return readService.retrieveOne(step.getId());
    }

    @Transactional
    @Override
    public PendingStepData cancel(Long id) {
        AppUser currentUser = context.authenticatedUser();
        PendingStep step = stepRepository.findById(id).orElseThrow(() -> new PendingStepNotFoundException(id));
        if ("completed".equals(step.getStatus())) {
            return readService.retrieveOne(step.getId());
        }
        if ("cancelado".equals(step.getStatus())) {
            return readService.retrieveOne(step.getId());
        }
        step.setStatus("cancelado");
        step.setCompletionDate(DateUtils.getAuditOffsetDateTime());
        String referencesWithCancel = appendCancelledToReferences(step.getReferences(), currentUser, DateUtils.getAuditOffsetDateTime());
        step.setReferences(referencesWithCancel);
        step = stepRepository.saveAndFlush(step);
        return readService.retrieveOne(step.getId());
    }

    /**
     * Merges cancelled_by (userId, username) and cancelled_at (ISO datetime) into the step's references JSON.
     */
    private String appendCancelledToReferences(String existingReferences, AppUser cancelledBy, OffsetDateTime cancelledAt) {
        JsonObject refs;
        if (StringUtils.isNotBlank(existingReferences)) {
            try {
                refs = fromJsonHelper.parse(existingReferences).getAsJsonObject().deepCopy();
            } catch (Exception e) {
                refs = new JsonObject();
            }
        } else {
            refs = new JsonObject();
        }
        JsonObject cancelledByObj = new JsonObject();
        if (cancelledBy != null) {
            if (cancelledBy.getId() != null) {
                cancelledByObj.addProperty("userId", cancelledBy.getId());
            }
            if (cancelledBy.getUsername() != null) {
                cancelledByObj.addProperty("username", cancelledBy.getUsername().trim());
            }
        }
        refs.add("cancelled_by", cancelledByObj);
        refs.addProperty("cancelled_at", cancelledAt != null ? cancelledAt.toString() : null);
        return fromJsonHelper.toJson(refs);
    }

    @Transactional
    @Override
    public PendingStepData complete(Long id, String json) {
        AppUser currentUser = context.authenticatedUser();
        String note = parseNoteFromRequest(json);

        PendingStep step = stepRepository.findById(id).orElseThrow(() -> new PendingStepNotFoundException(id));
        PendingFlow flow = step.getPendingFlow();
        if (flow == null) {
            throw new PendingStepNotFoundException(id);
        }
        if ("completed".equals(step.getStatus())) {
            return readService.retrieveOne(step.getId());
        }
        if (step.getPreviousStep() != null && !"completed".equals(step.getPreviousStep().getStatus())) {
            throw new IllegalStateException("Previous step must be completed first");
        }
        step.setStatus("completed");
        step.setCompletionDate(DateUtils.getAuditOffsetDateTime());
        if (note != null) {
            step.setNote(note);
        }
        step = stepRepository.saveAndFlush(step);
        flow.setLastCompletedStepId(step.getId());

        List<PendingStep> flowSteps = stepRepository.findByPendingFlowIdOrderById(flow.getId());
        PendingStep nextStep = null;
        PendingStep createdStep = null;
        for (int i = 0; i < flowSteps.size(); i++) {
            if (flowSteps.get(i).getId().equals(step.getId()) && i + 1 < flowSteps.size()) {
                nextStep = stepRepository.findById(flowSteps.get(i + 1).getId()).orElse(null);
                break;
            }
        }

        if (nextStep != null) {
            nextStep.setStatus("open");
            stepRepository.saveAndFlush(nextStep);
        } else {
            // Lazy step creation: create next step from blueprint if it exists
            PendingFlowBlueprint blueprint = flow.getPendingFlowBlueprint();
            if (blueprint != null && StringUtils.isNotBlank(blueprint.getSteps())) {
                JsonArray stepsArray = fromJsonHelper.parse(blueprint.getSteps()).getAsJsonArray();
                int currentOrder = findStepOrderInBlueprint(stepsArray, step.getName());
                if (currentOrder >= 0 && currentOrder + 1 < stepsArray.size()) {
                    JsonObject nextStepDef = stepsArray.get(currentOrder + 1).getAsJsonObject();
                    String nextStepName = fromJsonHelper.extractStringNamed("name", nextStepDef);
                    String nextStepDesc = fromJsonHelper.extractStringNamed("description", nextStepDef);
                    String nextStepReferences = resolveNextStepReferences(nextStepDef, step);

                    PendingStep newNext = PendingStep.newInstance();
                    newNext.setName(nextStepName);
                    newNext.setDescription(nextStepDesc);
                    newNext.setStatus("open");
                    newNext.setPendingFlow(flow);
                    newNext.setPreviousStep(step);
                    newNext.setCreator(currentUser);
                    newNext.setCreationDate(DateUtils.getAuditOffsetDateTime());
                    newNext.setReferences(nextStepReferences);
                    newNext.setOffice(step.getOffice());

                    applyNextStepOverridesFromRequest(newNext, json, currentUser);
                    newNext = stepRepository.saveAndFlush(newNext);
                    nextStep = newNext;
                    createdStep = newNext;

                    List<Long> stepIds = parseStepIds(flow.getStepsId());
                    stepIds.add(newNext.getId());
                    flow.setStepsId(fromJsonHelper.toJson(stepIds));
                } else {
                    flow.setStatus("completed");
                }
            } else {
                flow.setStatus("completed");
            }
        }
        flowRepository.saveAndFlush(flow);

        // Type-specific callbacks from the flow's builder (e.g. custom business logic on completion)
        PendingFlowBlueprint blueprint = flow.getPendingFlowBlueprint();
        if (blueprint != null) {
            PendingFlowBuilder builder = builderRegistry.getBuilder(blueprint);
            builder.onStepCompleted(flow, step, nextStep);
            if (createdStep != null) {
                builder.onNextStepCreated(flow, createdStep);
            }
        }

        return readService.retrieveOne(step.getId());
    }

    private String parseNoteFromRequest(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            JsonObject object = fromJsonHelper.parse(json).getAsJsonObject();
            return fromJsonHelper.extractStringNamed("note", object);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Applies optional next-step fields from the complete request JSON. Expects a "nextStep" object
     * with optional: responsableUserId, dueDate, references, note, officeId. Falls back to current user
     * and nulls when not provided.
     */
    private void applyNextStepOverridesFromRequest(PendingStep newNext, String json, AppUser currentUser) {
        newNext.setNote(null);
        newNext.setDueDate(null);
        newNext.setResponsableUser(currentUser);
        if (json == null || json.isBlank()) {
            return;
        }
        try {
            JsonObject object = fromJsonHelper.parse(json).getAsJsonObject();
            if (!object.has("nextStep") || !object.get("nextStep").isJsonObject()) {
                return;
            }
            JsonObject nextStep = object.getAsJsonObject("nextStep");
            if (nextStep.has("officeId")) {
                Long officeId = fromJsonHelper.extractLongNamed("officeId", nextStep);
                if (officeId != null) {
                    Office office = officeRepositoryWrapper.findOneWithNotFoundDetection(officeId);
                    newNext.setOffice(office);
                } else {
                    newNext.setOffice(null);
                }
            }
            if (nextStep.has("responsableUserId")) {
                Long responsableUserId = fromJsonHelper.extractLongNamed("responsableUserId", nextStep);
                if (responsableUserId != null) {
                    AppUser responsable = appUserRepository.findById(responsableUserId).orElse(null);
                    if (responsable != null) {
                        newNext.setResponsableUser(responsable);
                    }
                }
            }
            if (nextStep.has("dueDate") && !nextStep.get("dueDate").isJsonNull()) {
                String dueDateStr = fromJsonHelper.extractStringNamed("dueDate", nextStep);
                if (StringUtils.isNotBlank(dueDateStr)) {
                    try {
                        newNext.setDueDate(OffsetDateTime.parse(dueDateStr));
                    } catch (Exception ignored) {
                        // leave null on parse error
                    }
                }
            }
            if (nextStep.has("references")) {
                JsonElement refs = nextStep.get("references");
                if (refs != null && !refs.isJsonNull()) {
                    newNext.setReferences(fromJsonHelper.toJson(refs));
                }
            }
            if (nextStep.has("note")) {
                newNext.setNote(fromJsonHelper.extractStringNamed("note", nextStep));
            }
        } catch (Exception ignored) {
            // keep defaults when parsing fails
        }
    }

    private int findStepOrderInBlueprint(JsonArray stepsArray, String stepName) {
        for (int i = 0; i < stepsArray.size(); i++) {
            JsonObject stepDef = stepsArray.get(i).getAsJsonObject();
            if (stepName.equals(fromJsonHelper.extractStringNamed("name", stepDef))) {
                return i;
            }
        }
        return -1;
    }

    /**
     * Resolves references for the next step from the blueprint. For reference_type "prev_step"
     * copies the completed step's references; otherwise passthrough of reference_fields.
     */
    private String resolveNextStepReferences(JsonObject nextStepDef, PendingStep completedStep) {
        String referenceType = nextStepDef.has("reference_type")
                ? fromJsonHelper.extractStringNamed("reference_type", nextStepDef) : null;
        if ("prev_step".equals(referenceType) && completedStep.getReferences() != null) {
            return completedStep.getReferences();
        }
        if (nextStepDef.has("reference_fields")) {
            return fromJsonHelper.toJson(nextStepDef.get("reference_fields"));
        }
        return null;
    }

    private List<Long> parseStepIds(String stepsIdJson) {
        List<Long> ids = new ArrayList<>();
        if (StringUtils.isBlank(stepsIdJson)) {
            return ids;
        }
        JsonArray arr = fromJsonHelper.parse(stepsIdJson).getAsJsonArray();
        for (int i = 0; i < arr.size(); i++) {
            ids.add(arr.get(i).getAsLong());
        }
        return ids;
    }
}
