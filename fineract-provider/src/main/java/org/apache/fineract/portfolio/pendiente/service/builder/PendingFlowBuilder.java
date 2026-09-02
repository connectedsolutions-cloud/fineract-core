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

import org.apache.fineract.portfolio.pendiente.domain.PendingFlow;
import org.apache.fineract.portfolio.pendiente.domain.PendingFlowBlueprint;
import org.apache.fineract.portfolio.pendiente.domain.PendingStep;

/**
 * Builds a pending flow and its first step from a blueprint and request. Each concrete builder supports one or more
 * blueprint types (e.g. by name) and owns the reference-processing logic for that type.
 * <p>
 * Optional callbacks {@link #onStepCompleted} and {@link #onNextStepCreated} allow type-specific business logic when a
 * step is completed or when a next step is created (e.g. lazy-created from blueprint). Override them in your builder to
 * apply custom actions; default implementations are no-op.
 */
public interface PendingFlowBuilder {

    /**
     * Order when resolving builder (lower = higher priority). Default/fallback builders should return a high value so
     * type-specific builders are chosen first.
     */
    default int getOrder() {
        return 0;
    }

    /**
     * Whether this builder supports the given blueprint (e.g. by blueprint name).
     */
    boolean supports(PendingFlowBlueprint blueprint);

    /**
     * Build the flow and first step. The caller persists them and sets flow.stepsId to the first step's id.
     */
    PendingFlowBuildResult build(PendingFlowBlueprint blueprint, PendingFlowBuildRequest request, PendingFlowBuildContext context);

    /**
     * Called after a step is marked completed and the flow is updated. Override to run type-specific business logic
     * (e.g. update related entities, send notifications).
     *
     * @param flow
     *            the pending flow
     * @param completedStep
     *            the step that was just completed
     * @param nextStepOrNull
     *            the next step that is now open, or null if the flow is completed or there is no next step
     */
    default void onStepCompleted(PendingFlow flow, PendingStep completedStep, PendingStep nextStepOrNull) {
        // no-op by default
    }

    /**
     * Called when a new next step was created in this request (lazy creation from blueprint). Override to run
     * type-specific logic for the newly created step.
     *
     * @param flow
     *            the pending flow
     * @param newStep
     *            the step that was just created and saved
     */
    default void onNextStepCreated(PendingFlow flow, PendingStep newStep) {
        // no-op by default
    }
}
