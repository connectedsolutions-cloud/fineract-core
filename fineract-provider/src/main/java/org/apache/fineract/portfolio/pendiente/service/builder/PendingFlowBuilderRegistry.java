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
package org.apache.fineract.portfolio.pendiente.service.builder;

import java.util.Comparator;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.springframework.stereotype.Component;

/**
 * Registry of pending flow builders. Returns the first builder that supports the given
 * blueprint (type-specific builders have lower order, default builder has highest order).
 */
@Component
@RequiredArgsConstructor
public class PendingFlowBuilderRegistry {

    private final List<PendingFlowBuilder> builders;

    public PendingFlowBuilder getBuilder(PendingFlowBlueprint blueprint) {
        return builders.stream().sorted(Comparator.comparingInt(PendingFlowBuilder::getOrder))
                .filter(b -> b.supports(blueprint)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "No builder registered for blueprint: " + blueprint.getName()));
    }
}
