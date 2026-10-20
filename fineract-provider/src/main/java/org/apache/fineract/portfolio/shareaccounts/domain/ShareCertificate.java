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
package org.apache.fineract.portfolio.shareaccounts.domain;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.portfolio.client.domain.Client;

@Entity
@Table(name = "credesal_share_certificate")
@Getter
@Setter
@NoArgsConstructor
public class ShareCertificate extends AbstractPersistableCustom<Long> {

    public static final String SOURCE_FINERACT = "fineract";
    public static final String STATUS_OPENED = "APERTURADO";
    public static final String STATUS_ISSUED = "EMITIDO";
    public static final String STATUS_PAID = "PAGADO";

    @Column(name = "source_system", length = 32, nullable = false)
    private String sourceSystem;

    @Column(name = "source_key", length = 500, nullable = false)
    private String sourceKey;

    @Column(name = "source_hash", length = 64, nullable = false)
    private String sourceHash;

    @ManyToOne(optional = false)
    @JoinColumn(name = "client_id", nullable = false)
    private Client client;

    @ManyToOne
    @JoinColumn(name = "share_account_id")
    private ShareAccount shareAccount;

    @Column(name = "share_type_name", length = 50)
    private String shareTypeName;

    @Column(name = "status_name", length = 25)
    private String statusName;

    @Column(name = "share_class_code", length = 8)
    private String shareClassCode;

    @Column(name = "native_status", length = 25)
    private String nativeStatus;

    @Column(name = "office_id")
    private Long officeId;

    @Column(name = "promoter_staff_id")
    private Long promoterStaffId;

    @Column(name = "book_id")
    private Integer bookId;

    @Column(name = "provisional_number", length = 50)
    private String provisionalNumber;

    @Column(name = "certificate_number", length = 50)
    private String certificateNumber;

    @Column(name = "certificate_date")
    private LocalDate certificateDate;

    @Column(name = "unit_price", scale = 2, precision = 10)
    private BigDecimal unitPrice;

    @Column(name = "represented_shares", scale = 2, precision = 18)
    private BigDecimal representedShares;

    @Column(name = "initial_share_number", length = 50)
    private String initialShareNumber;

    @Column(name = "final_share_number", length = 50)
    private String finalShareNumber;

    @Column(name = "share_serial_start")
    private Long shareSerialStart;

    @Column(name = "share_serial_end")
    private Long shareSerialEnd;

    @Column(name = "subscribed_shares", scale = 2, precision = 18)
    private BigDecimal subscribedShares;

    @Column(name = "subscribed_balance", scale = 2, precision = 19)
    private BigDecimal subscribedBalance;

    @Column(name = "paid_shares", scale = 2, precision = 18)
    private BigDecimal paidShares;

    @Column(name = "paid_balance", scale = 2, precision = 19)
    private BigDecimal paidBalance;

    @Column(name = "folio")
    private Integer folio;

    @Column(name = "line_number")
    private Integer lineNumber;

    @Column(name = "series", length = 25)
    private String series;

    @Column(name = "book_number", length = 25)
    private String bookNumber;

    @Column(name = "book_date")
    private LocalDate bookDate;

    @Column(name = "current_balance", scale = 2, precision = 19)
    private BigDecimal currentBalance;

    @Column(name = "pledged_balance", scale = 2, precision = 19)
    private BigDecimal pledgedBalance;

    @Column(name = "printed")
    private Boolean printed;

    @Column(name = "printed_at")
    private LocalDateTime printedAt;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @OneToMany(mappedBy = "certificate", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.LAZY)
    private List<ShareCertificateBeneficiary> beneficiaries = new ArrayList<>();

    public void addBeneficiary(final ShareCertificateBeneficiary beneficiary) {
        beneficiary.setCertificate(this);
        this.beneficiaries.add(beneficiary);
    }
}
