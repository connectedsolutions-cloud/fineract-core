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
package org.apache.fineract.portfolio.pendiente.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.persistence.converter.JsonbStringAttributeConverter;

@Entity
@Table(name = "m_pending_flow_blueprint")
public class PendingFlowBlueprint extends AbstractPersistableCustom<Long> {

    @Column(name = "status", nullable = false, length = 50)
    private String status;

    @Column(name = "name", nullable = false, length = 255)
    private String name;

    @Column(name = "version", length = 50)
    private String version;

    @Column(name = "last_step_name", length = 255)
    private String lastStepName;

    @Column(name = "steps", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String steps;

    @Column(name = "triggers", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String triggers;

    protected PendingFlowBlueprint() {}

    /** Factory for use by write services outside the domain package. */
    public static PendingFlowBlueprint newInstance() {
        return new PendingFlowBlueprint();
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getVersion() {
        return version;
    }

    public void setVersion(String version) {
        this.version = version;
    }

    public String getLastStepName() {
        return lastStepName;
    }

    public void setLastStepName(String lastStepName) {
        this.lastStepName = lastStepName;
    }

    public String getSteps() {
        return steps;
    }

    public void setSteps(String steps) {
        this.steps = steps;
    }

    public String getTriggers() {
        return triggers;
    }

    public void setTriggers(String triggers) {
        this.triggers = triggers;
    }
}
