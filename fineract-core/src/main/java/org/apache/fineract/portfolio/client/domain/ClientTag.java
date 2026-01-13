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
package org.apache.fineract.portfolio.client.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.Getter;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractAuditableWithUTCDateTimeCustom;

@Entity
@Table(name = "m_client_tag", uniqueConstraints = { @UniqueConstraint(columnNames = { "name" }, name = "uk_client_tag_name") })
@Getter
@Setter
public class ClientTag extends AbstractAuditableWithUTCDateTimeCustom<Long> {

    @Column(name = "name", length = 100, nullable = false, unique = true)
    private String name;

    @Column(name = "tag_group", length = 50, nullable = false)
    private String tagGroup;

    @Column(name = "description", length = 500)
    private String description;

    @Column(name = "is_active", nullable = false)
    private Boolean isActive;

    protected ClientTag() {
        // Protected constructor for JPA
    }

    public ClientTag(final String name, final String tagGroup, final String description) {
        this.name = name;
        this.tagGroup = tagGroup;
        this.description = description;
        this.isActive = true;
    }

    public void deactivate() {
        this.isActive = false;
    }

    public void activate() {
        this.isActive = true;
    }

    public boolean isActive() {
        return Boolean.TRUE.equals(this.isActive);
    }
}
