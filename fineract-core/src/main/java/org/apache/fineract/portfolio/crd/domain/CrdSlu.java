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
package org.apache.fineract.portfolio.crd.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Objects;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "crd_slu")
@Getter
@Setter
@NoArgsConstructor
public class CrdSlu implements Serializable {

    @Id
    @Column(name = "id_slu", nullable = false)
    private Short id;

    @Column(name = "id_empresa", length = 3)
    private String idEmpresa;

    @ManyToOne(fetch = FetchType.EAGER)
    @JoinColumn(name = "id_tipo_linea", referencedColumnName = "id_tipo_linea")
    private CrdTipoLinea tipoLinea;

    @Column(name = "descripcion", length = 500)
    private String descripcion;

    @Column(name = "monto_ini", precision = 18, scale = 2)
    private BigDecimal montoIni;

    @Column(name = "monto_fin", precision = 18, scale = 2)
    private BigDecimal montoFin;

    @Column(name = "tea", precision = 8, scale = 2)
    private BigDecimal tea;

    @Column(name = "activo")
    private Boolean activo;

    @Column(name = "slu", length = 5)
    private String slu;

    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (!(o instanceof CrdSlu crdSlu)) {
            return false;
        }
        return Objects.equals(id, crdSlu.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}
