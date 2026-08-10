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
package org.apache.fineract.portfolio.crd.data;

import java.io.Serializable;
import java.math.BigDecimal;
import lombok.Getter;

@Getter
public final class CrdSluData implements Serializable {

    private final Short id;
    private final String idEmpresa;
    private final String idTipoLinea;
    private final String descripcion;
    private final BigDecimal montoIni;
    private final BigDecimal montoFin;
    private final BigDecimal tea;
    private final Boolean activo;
    private final String slu;

    public static CrdSluData instance(final Short id, final String idEmpresa, final String idTipoLinea, final String descripcion,
            final BigDecimal montoIni, final BigDecimal montoFin, final BigDecimal tea, final Boolean activo, final String slu) {
        return new CrdSluData(id, idEmpresa, idTipoLinea, descripcion, montoIni, montoFin, tea, activo, slu);
    }

    private CrdSluData(final Short id, final String idEmpresa, final String idTipoLinea, final String descripcion,
            final BigDecimal montoIni, final BigDecimal montoFin, final BigDecimal tea, final Boolean activo, final String slu) {
        this.id = id;
        this.idEmpresa = idEmpresa;
        this.idTipoLinea = idTipoLinea;
        this.descripcion = descripcion;
        this.montoIni = montoIni;
        this.montoFin = montoFin;
        this.tea = tea;
        this.activo = activo;
        this.slu = slu;
    }
}
