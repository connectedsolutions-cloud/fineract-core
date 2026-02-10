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
@Table(name = "m_pending_step")
public class PendingStep extends AbstractPersistableCustom<Long> {

    @Column(name = "name", nullable = false, length = 255)
    private String name;

    @Column(name = "status", nullable = false, length = 50)
    private String status;

    @Column(name = "description", columnDefinition = "text")
    private String description;

    @Column(name = "note", columnDefinition = "text")
    private String note;

    @ManyToOne
    @JoinColumn(name = "pending_flow_id", nullable = false)
    private PendingFlow pendingFlow;

    @ManyToOne
    @JoinColumn(name = "previous_step_id")
    private PendingStep previousStep;

    @ManyToOne
    @JoinColumn(name = "creator_id", nullable = false)
    private AppUser creator;

    @Column(name = "creation_date", nullable = false)
    private OffsetDateTime creationDate;

    @Column(name = "due_date")
    private OffsetDateTime dueDate;

    @ManyToOne
    @JoinColumn(name = "responsable_user_id")
    private AppUser responsableUser;

    @Column(name = "references", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String references;

    protected PendingStep() {}

    /** Factory for use by write services outside the domain package. */
    public static PendingStep newInstance() {
        return new PendingStep();
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public String getNote() {
        return note;
    }

    public void setNote(String note) {
        this.note = note;
    }

    public PendingFlow getPendingFlow() {
        return pendingFlow;
    }

    public void setPendingFlow(PendingFlow pendingFlow) {
        this.pendingFlow = pendingFlow;
    }

    public PendingStep getPreviousStep() {
        return previousStep;
    }

    public void setPreviousStep(PendingStep previousStep) {
        this.previousStep = previousStep;
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

    public AppUser getResponsableUser() {
        return responsableUser;
    }

    public void setResponsableUser(AppUser responsableUser) {
        this.responsableUser = responsableUser;
    }

    public String getReferences() {
        return references;
    }

    public void setReferences(String references) {
        this.references = references;
    }
}
