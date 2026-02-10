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

import java.util.List;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowBlueprintData;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprintRepository;
import org.apache.fineract.portfolio.pendiente.exception.PendingFlowBlueprintNotFoundException;
import org.springframework.stereotype.Service;

@RequiredArgsConstructor
@Service
public class PendingFlowBlueprintReadPlatformServiceImpl implements PendingFlowBlueprintReadPlatformService {

    private final PendingFlowBlueprintRepository repository;
    private final PlatformSecurityContext context;

    @Override
    public List<PendingFlowBlueprintData> retrieveAll() {
        context.authenticatedUser();
        return repository.findAll().stream().map(this::mapToData).collect(Collectors.toList());
    }

    @Override
    public PendingFlowBlueprintData retrieveOne(Long id) {
        context.authenticatedUser();
        PendingFlowBlueprint entity = repository.findById(id)
                .orElseThrow(() -> new PendingFlowBlueprintNotFoundException(id));
        return mapToData(entity);
    }

    private PendingFlowBlueprintData mapToData(PendingFlowBlueprint entity) {
        PendingFlowBlueprintData data = new PendingFlowBlueprintData();
        data.setId(entity.getId());
        data.setStatus(entity.getStatus());
        data.setName(entity.getName());
        data.setVersion(entity.getVersion());
        data.setLastStepName(entity.getLastStepName());
        data.setSteps(entity.getSteps());
        data.setTriggers(entity.getTriggers());
        return data;
    }
}
