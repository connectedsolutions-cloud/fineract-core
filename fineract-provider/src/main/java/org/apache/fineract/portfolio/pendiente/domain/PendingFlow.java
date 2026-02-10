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
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.persistence.converter.JsonbStringAttributeConverter;
import org.apache.fineract.useradministration.domain.AppUser;

@Entity
@Table(name = "m_pending_flow")
public class PendingFlow extends AbstractPersistableCustom<Long> {

    @Column(name = "name", nullable = false, length = 255)
    private String name;

    @Column(name = "description", columnDefinition = "text")
    private String description;

    @ManyToOne
    @JoinColumn(name = "creator_id", nullable = false)
    private AppUser creator;

    @Column(name = "creation_date", nullable = false)
    private OffsetDateTime creationDate;

    @Column(name = "due_date")
    private OffsetDateTime dueDate;

    @Column(name = "status", nullable = false, length = 50)
    private String status;

    @ManyToOne
    @JoinColumn(name = "pending_flow_blueprint_id", nullable = false)
    private PendingFlowBlueprint pendingFlowBlueprint;

    @Column(name = "steps_id", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String stepsId;

    @Column(name = "last_completed_step_id")
    private Long lastCompletedStepId;

    protected PendingFlow() {}

    /** Factory for use by write services outside the domain package. */
    public static PendingFlow newInstance() {
        return new PendingFlow();
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public AppUser getCreator() {
        return creator;
    }

    public void setCreator(AppUser creator) {
        this.creator = creator;
    }

    public OffsetDateTime getCreationDate() {
        return creationDate;
    }

    public void setCreationDate(OffsetDateTime creationDate) {
        this.creationDate = creationDate;
    }

    public OffsetDateTime getDueDate() {
        return dueDate;
    }

    public void setDueDate(OffsetDateTime dueDate) {
        this.dueDate = dueDate;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public PendingFlowBlueprint getPendingFlowBlueprint() {
        return pendingFlowBlueprint;
    }

    public void setPendingFlowBlueprint(PendingFlowBlueprint pendingFlowBlueprint) {
        this.pendingFlowBlueprint = pendingFlowBlueprint;
    }

    public String getStepsId() {
        return stepsId;
    }

    public void setStepsId(String stepsId) {
        this.stepsId = stepsId;
    }

    public Long getLastCompletedStepId() {
        return lastCompletedStepId;
    }

    public void setLastCompletedStepId(Long lastCompletedStepId) {
        this.lastCompletedStepId = lastCompletedStepId;
    }
}
