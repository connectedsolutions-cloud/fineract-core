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
package org.apache.fineract.portfolio.crd.service;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Collection;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.crd.data.CrdSluData;
import org.apache.fineract.portfolio.crd.data.CrdTipoLineaData;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

@RequiredArgsConstructor
public class CrdCatalogReadPlatformServiceImpl implements CrdCatalogReadPlatformService {

    private final JdbcTemplate jdbcTemplate;
    private final PlatformSecurityContext context;

    private static final class CrdTipoLineaMapper implements RowMapper<CrdTipoLineaData> {

        public String schema() {
            return " t.id_tipo_linea as id, t.nombre_tipo_linea as nombreTipoLinea, t.descripcion_tipo_linea as descripcionTipoLinea, "
                    + "t.es_tarjeta_socio_activo as esTarjetaSocioActivo, t.cs_puntos as csPuntos from crd_tipo_linea t ";
        }

        @Override
        public CrdTipoLineaData mapRow(final ResultSet rs, @SuppressWarnings("unused") final int rowNum) throws SQLException {
            final String id = rs.getString("id");
            final String nombreTipoLinea = rs.getString("nombreTipoLinea");
            final String descripcionTipoLinea = rs.getString("descripcionTipoLinea");
            final String esTarjetaSocioActivo = rs.getString("esTarjetaSocioActivo");
            final BigDecimal csPuntos = rs.getBigDecimal("csPuntos");
            return CrdTipoLineaData.instance(id, nombreTipoLinea, descripcionTipoLinea, esTarjetaSocioActivo, csPuntos);
        }
    }

    private static final class CrdSluMapper implements RowMapper<CrdSluData> {

        public String schema() {
            return " s.id_slu as id, s.id_empresa as idEmpresa, s.id_tipo_linea as idTipoLinea, s.descripcion as descripcion, "
                    + "s.monto_ini as montoIni, s.monto_fin as montoFin, s.tea as tea, s.activo as activo, s.slu as slu from crd_slu s ";
        }

        @Override
        public CrdSluData mapRow(final ResultSet rs, @SuppressWarnings("unused") final int rowNum) throws SQLException {
            final Short id = rs.getShort("id");
            final String idEmpresa = rs.getString("idEmpresa");
            final String idTipoLinea = rs.getString("idTipoLinea");
            final String descripcion = rs.getString("descripcion");
            final BigDecimal montoIni = rs.getBigDecimal("montoIni");
            final BigDecimal montoFin = rs.getBigDecimal("montoFin");
            final BigDecimal tea = rs.getBigDecimal("tea");
            final Boolean activo = rs.getObject("activo") == null ? null : rs.getBoolean("activo");
            final String slu = rs.getString("slu");
            return CrdSluData.instance(id, idEmpresa, idTipoLinea, descripcion, montoIni, montoFin, tea, activo, slu);
        }
    }

    @Override
    public Collection<CrdTipoLineaData> retrieveAllTipoLineas() {
        this.context.authenticatedUser();
        final CrdTipoLineaMapper rm = new CrdTipoLineaMapper();
        final String sql = "select " + rm.schema() + " order by t.id_tipo_linea";
        return this.jdbcTemplate.query(sql, rm); // NOSONAR
    }

    @Override
    public Collection<CrdSluData> retrieveAllActiveSlus() {
        this.context.authenticatedUser();
        final CrdSluMapper rm = new CrdSluMapper();
        final String sql = "select " + rm.schema() + " where s.activo = true order by s.slu, s.monto_ini";
        return this.jdbcTemplate.query(sql, rm); // NOSONAR
    }

    @Override
    public Collection<CrdSluData> retrieveLoanProductSlus(final Long loanProductId) {
        this.context.authenticatedUser();
        final CrdSluMapper rm = new CrdSluMapper();
        final String sql = "select " + rm.schema()
                + " join m_product_loan_slu pls on pls.id_slu = s.id_slu where pls.product_loan_id = ? order by s.slu, s.monto_ini";
        return this.jdbcTemplate.query(sql, rm, loanProductId); // NOSONAR
    }
}
