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
package org.apache.fineract.portfolio.collateralmanagement.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_collateral_valuation")
@Getter
@Setter
@NoArgsConstructor
public class CollateralValuation extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "asset_id", nullable = false)
    private ClientCollateralAsset asset;
    @Column(name = "external_id", length = 100, unique = true)
    private String externalId;
    @Column(name = "valuation_type", nullable = false, length = 20)
    private String valuationType;
    @Column(name = "valuation_date")
    private LocalDate valuationDate;
    @Column(name = "currency_code", nullable = false, length = 3)
    private String currencyCode;
    @Column(name = "total_value", nullable = false, precision = 19, scale = 6)
    private BigDecimal totalValue;
    @Column(name = "land_value", precision = 19, scale = 6)
    private BigDecimal landValue;
    @Column(name = "construction_value", precision = 19, scale = 6)
    private BigDecimal constructionValue;
    @Column(name = "market_value", precision = 19, scale = 6)
    private BigDecimal marketValue;
    @Column(name = "sale_value", precision = 19, scale = 6)
    private BigDecimal saleValue;
    @Column(name = "appraiser", length = 200)
    private String appraiser;
    @Column(name = "appraisal_company", length = 200)
    private String appraisalCompany;
    @Column(name = "appraiser_opinion", length = 1000)
    private String appraiserOpinion;
    @Column(name = "appraisal_cost", precision = 19, scale = 6)
    private BigDecimal appraisalCost;
    @Column(name = "status", nullable = false, length = 20)
    private String status;
    @Column(name = "supersedes_valuation_id")
    private Long supersedesValuationId;
    @Column(name = "createdby_id")
    private Long createdById;
    @Column(name = "created_date")
    private LocalDateTime createdDate;
    @Column(name = "lastmodifiedby_id")
    private Long lastModifiedById;
    @Column(name = "lastmodified_date")
    private LocalDateTime lastModifiedDate;

    public CollateralValuation(ClientCollateralAsset asset, Long userId, LocalDateTime now) {
        this.asset = asset;
        this.createdById = userId;
        this.createdDate = now;
        this.status = "DRAFT";
    }
}
