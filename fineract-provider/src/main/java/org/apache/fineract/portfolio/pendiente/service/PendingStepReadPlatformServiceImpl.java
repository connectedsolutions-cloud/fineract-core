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
import org.apache.fineract.portfolio.pendiente.data.PendingStepData;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;
import org.apache.fineract.portfolio.pendiente.domain.PendingStepRepository;
import org.apache.fineract.portfolio.pendiente.exception.PendingStepNotFoundException;
import org.springframework.stereotype.Service;

@RequiredArgsConstructor
@Service
public class PendingStepReadPlatformServiceImpl implements PendingStepReadPlatformService {

    private final PendingStepRepository repository;
    private final PlatformSecurityContext context;

    @Override
    public List<PendingStepData> retrieveByFlowId(Long pendingFlowId) {
        context.authenticatedUser();
        return repository.findByPendingFlowIdOrderById(pendingFlowId).stream().map(this::mapToData)
                .collect(Collectors.toList());
    }

    @Override
    public List<PendingStepData> retrieveMySteps(Long userId, List<String> statuses) {
        context.authenticatedUser();
        List<String> statusList = statuses != null && !statuses.isEmpty() ? statuses : List.of("open", "pending");
        return repository.findByResponsableUserIdAndStatusInOrderByCreationDateDesc(userId, statusList).stream()
                .map(this::mapToData).collect(Collectors.toList());
    }

    @Override
    public PendingStepData retrieveOne(Long id) {
        context.authenticatedUser();
        PendingStep step = repository.findById(id).orElseThrow(() -> new PendingStepNotFoundException(id));
        return mapToData(step);
    }

    private PendingStepData mapToData(PendingStep entity) {
        PendingStepData data = new PendingStepData();
        data.setId(entity.getId());
        data.setName(entity.getName());
        data.setStatus(entity.getStatus());
        data.setDescription(entity.getDescription());
        data.setNote(entity.getNote());
        data.setPendingFlowId(entity.getPendingFlow() != null ? entity.getPendingFlow().getId() : null);
        data.setPreviousStepId(entity.getPreviousStep() != null ? entity.getPreviousStep().getId() : null);
        data.setCreatorId(entity.getCreator() != null ? entity.getCreator().getId() : null);
        data.setCreatorName(entity.getCreator() != null ? entity.getCreator().getDisplayName() : null);
        data.setCreationDate(entity.getCreationDate());
        data.setDueDate(entity.getDueDate());
        data.setResponsableUserId(entity.getResponsableUser() != null ? entity.getResponsableUser().getId() : null);
        data.setResponsableUserName(
                entity.getResponsableUser() != null ? entity.getResponsableUser().getDisplayName() : null);
        data.setReferences(entity.getReferences());
        return data;
    }
}
