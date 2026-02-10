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

import org.apache.fineract.portfolio.pendiente.data.PendingFlowData;

public interface PendingFlowWritePlatformService {

    PendingFlowData createFromBlueprint(Long blueprintId, String json);

    /**
     * Creates only the pending flow and its first step using the builder for the blueprint.
     * Requires responsableUserId in the request body; dueDate and reference items are optional.
     */
    PendingFlowData createFlowAndFirstStep(Long blueprintId, String json);
}
