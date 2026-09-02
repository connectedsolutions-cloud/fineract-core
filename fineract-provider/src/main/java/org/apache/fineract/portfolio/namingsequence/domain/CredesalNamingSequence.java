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
package org.apache.fineract.portfolio.namingsequence.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "credesal_naming_sequence", uniqueConstraints = {
        @UniqueConstraint(columnNames = { "namespace", "prefix" }, name = "uk_credesal_naming_sequence_ns_prefix") })
@Getter
@Setter
@NoArgsConstructor
public class CredesalNamingSequence extends AbstractPersistableCustom<Long> {

    @Column(name = "namespace", length = 32, nullable = false)
    private String namespace;

    @Column(name = "prefix", length = 16, nullable = false)
    private String prefix;

    @Column(name = "last_ordinal", nullable = false)
    private Integer lastOrdinal;

    public static CredesalNamingSequence create(final String namespace, final String prefix, final int lastOrdinal) {
        final CredesalNamingSequence sequence = new CredesalNamingSequence();
        sequence.namespace = namespace;
        sequence.prefix = prefix;
        sequence.lastOrdinal = lastOrdinal;
        return sequence;
    }
}
