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
package org.apache.fineract.portfolio.comite.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.persistence.converter.JsonbStringAttributeConverter;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.useradministration.domain.AppUser;

@Entity
@Table(name = "m_sesiones_comite")
@NoArgsConstructor
@Getter
@Setter
public class SesionComite extends AbstractPersistableCustom<Long> {

    @ManyToOne
    @JoinColumn(name = "office_id", nullable = false)
    private Office office;

    @Column(name = "integrantes", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String integrantes;

    @ManyToOne
    @JoinColumn(name = "creator_id", nullable = false)
    private AppUser creator;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;

    @Column(name = "selection", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String selection;

    @Column(name = "description", columnDefinition = "text")
    private String description;

    @Column(name = "sesion_start_date")
    private OffsetDateTime sesionStartDate;

    @Column(name = "status", nullable = false, length = 50)
    private String status;

    @Column(name = "closing_date")
    private OffsetDateTime closingDate;

    @Column(name = "output", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String output;

    @Column(name = "type", nullable = false, length = 100)
    private String type = "comite_otorgamiento";

    @Column(name = "name", nullable = false, length = 255)
    private String name;
}
