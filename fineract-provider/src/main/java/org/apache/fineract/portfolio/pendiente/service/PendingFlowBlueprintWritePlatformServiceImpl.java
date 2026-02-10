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

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowBlueprintData;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprintRepository;
import org.apache.fineract.portfolio.pendiente.exception.PendingFlowBlueprintNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class PendingFlowBlueprintWritePlatformServiceImpl implements PendingFlowBlueprintWritePlatformService {

    private final PendingFlowBlueprintRepository repository;
    private final PlatformSecurityContext context;
    private final FromJsonHelper fromJsonHelper;
    private final PendingFlowBlueprintReadPlatformService readService;

    @Transactional
    @Override
    public PendingFlowBlueprintData create(String json) {
        context.authenticatedUser();
        JsonObject object = fromJsonHelper.parse(json).getAsJsonObject();
        PendingFlowBlueprint entity = PendingFlowBlueprint.newInstance();
        entity.setStatus(stringOr(object, "status", "active"));
        entity.setName(fromJsonHelper.extractStringNamed("name", object));
        entity.setVersion(fromJsonHelper.extractStringNamed("version", object));
        entity.setLastStepName(fromJsonHelper.extractStringNamed("lastStepName", object));
        entity.setSteps(extractJsonString(object, "steps"));
        entity.setTriggers(extractJsonString(object, "triggers"));
        entity = repository.saveAndFlush(entity);
        return readService.retrieveOne(entity.getId());
    }

    @Transactional
    @Override
    public PendingFlowBlueprintData update(Long id, String json) {
        context.authenticatedUser();
        PendingFlowBlueprint entity = repository.findById(id)
                .orElseThrow(() -> new PendingFlowBlueprintNotFoundException(id));
        JsonObject object = fromJsonHelper.parse(json).getAsJsonObject();
        if (object.has("status")) {
            entity.setStatus(fromJsonHelper.extractStringNamed("status", object));
        }
        if (object.has("name")) {
            entity.setName(fromJsonHelper.extractStringNamed("name", object));
        }
        if (object.has("version")) {
            entity.setVersion(fromJsonHelper.extractStringNamed("version", object));
        }
        if (object.has("lastStepName")) {
            entity.setLastStepName(fromJsonHelper.extractStringNamed("lastStepName", object));
        }
        if (object.has("steps")) {
            entity.setSteps(extractJsonString(object, "steps"));
        }
        if (object.has("triggers")) {
            entity.setTriggers(extractJsonString(object, "triggers"));
        }
        entity = repository.saveAndFlush(entity);
        return readService.retrieveOne(entity.getId());
    }

    private static String stringOr(JsonObject object, String key, String defaultValue) {
        if (!object.has(key)) {
            return defaultValue;
        }
        JsonElement el = object.get(key);
        if (el == null || el.isJsonNull()) {
            return defaultValue;
        }
        String s = el.getAsString();
        return StringUtils.isBlank(s) ? defaultValue : s;
    }

    private String extractJsonString(JsonObject object, String key) {
        if (!object.has(key)) {
            return null;
        }
        JsonElement el = object.get(key);
        if (el == null || el.isJsonNull()) {
            return null;
        }
        if (el.isJsonArray() || el.isJsonObject()) {
            return fromJsonHelper.toJson(el);
        }
        return el.getAsString();
    }
}
