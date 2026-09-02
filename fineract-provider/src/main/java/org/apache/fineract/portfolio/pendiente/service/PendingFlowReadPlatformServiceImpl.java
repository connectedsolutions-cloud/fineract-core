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

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.pendiente.data.PendingFlowData;
import org.apache.fineract.portfolio.pendiente.data.PendingStepData;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowRepository;
import org.apache.fineract.portfolio.pendiente.exception.PendingFlowNotFoundException;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;

@RequiredArgsConstructor
@Service
public class PendingFlowReadPlatformServiceImpl implements PendingFlowReadPlatformService {

    private final PendingFlowRepository repository;
    private final PendingStepReadPlatformService stepReadService;
    private final PlatformSecurityContext context;

    @Override
    public List<PendingFlowData> retrieveAll(Long blueprintId, Long creatorId, String status) {
        context.authenticatedUser();
        List<PendingFlow> list;
        if (blueprintId != null) {
            list = repository.findByPendingFlowBlueprintIdOrderByCreationDateDesc(blueprintId);
        } else if (creatorId != null) {
            list = repository.findByCreatorIdOrderByCreationDateDesc(creatorId);
        } else if (status != null && !status.isEmpty()) {
            list = repository.findByStatusOrderByCreationDateDesc(status);
        } else {
            list = repository.findAll(Sort.by(Sort.Direction.DESC, "creationDate"));
        }
        return list.stream().map(pf -> mapToData(pf, false)).collect(Collectors.toList());
    }

    @Override
    public PendingFlowData retrieveOne(Long id, boolean includeSteps) {
        context.authenticatedUser();
        PendingFlow flow = repository.findById(id).orElseThrow(() -> new PendingFlowNotFoundException(id));
        PendingFlowData data = mapToData(flow, includeSteps);
        if (includeSteps) {
            List<PendingStepData> steps = stepReadService.retrieveByFlowId(id);
            data.setSteps(steps);
        }
        return data;
    }

    private PendingFlowData mapToData(PendingFlow entity, boolean includeSteps) {
        PendingFlowData data = new PendingFlowData();
        data.setId(entity.getId());
        data.setName(entity.getName());
        data.setDescription(entity.getDescription());
        data.setCreatorId(entity.getCreator() != null ? entity.getCreator().getId() : null);
        data.setCreatorName(entity.getCreator() != null ? entity.getCreator().getDisplayName() : null);
        data.setCreationDate(entity.getCreationDate());
        data.setDueDate(entity.getDueDate());
        data.setStatus(entity.getStatus());
        data.setPendingFlowBlueprintId(entity.getPendingFlowBlueprint() != null ? entity.getPendingFlowBlueprint().getId() : null);
        data.setBlueprintName(entity.getPendingFlowBlueprint() != null ? entity.getPendingFlowBlueprint().getName() : null);
        data.setStepsId(entity.getStepsId());
        data.setLastCompletedStepId(entity.getLastCompletedStepId());
        if (includeSteps) {
            data.setSteps(new ArrayList<>());
        }
        return data;
    }
}
