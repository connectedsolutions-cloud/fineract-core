/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor
 * license agreements. See the NOTICE file distributed with this work for
 * additional information regarding copyright ownership. The ASF licenses this
 * file to you under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain a
 * copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.accounting.journalentry.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;

@Entity
@Getter
@Table(name = "credesal_gl_auxiliar")
public class GlAuxiliar {

    @Id
    @Column(name = "code", length = 32)
    private String code;

    @Column(name = "name", length = 100, nullable = false)
    private String name;

    @Column(name = "active", nullable = false)
    private boolean active;

    @Column(name = "manual_allowed", nullable = false)
    private boolean manualAllowed;

    @Column(name = "historical_arissto_code", nullable = false)
    private boolean historicalArisstoCode;

    protected GlAuxiliar() {}
}
