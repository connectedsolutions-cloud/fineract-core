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

import java.time.OffsetDateTime;
import java.util.Collections;
import java.util.Map;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * Input for building a pending flow and its first step. Contains mandatory responsable user id,
 * optional due date, optional name/description, and blueprint-specific reference items.
 */
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PendingFlowBuildRequest {

    private Long responsableUserId;
    private OffsetDateTime dueDate;
    private String name;
    private String description;

    /** Optional office id for the first step. */
    private Long officeId;

    /**
     * Blueprint-specific reference items (e.g. sesionComiteId, entity ids). Keys are
     * builder-specific; parsed from the request body.
     */
    @Builder.Default
    private Map<String, Object> references = Collections.emptyMap();

    public Object getReference(String key) {
        return references == null ? null : references.get(key);
    }

    public Long getReferenceLong(String key) {
        Object v = getReference(key);
        if (v == null) {
            return null;
        }
        if (v instanceof Number) {
            return ((Number) v).longValue();
        }
        if (v instanceof String) {
            try {
                return Long.parseLong((String) v);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }
}
