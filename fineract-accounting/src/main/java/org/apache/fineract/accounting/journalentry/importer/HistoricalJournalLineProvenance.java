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
package org.apache.fineract.accounting.journalentry.importer;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.office.domain.Office;

@Entity
@Table(name = "credesal_arissto_gl_journal_line")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class HistoricalJournalLineProvenance extends AbstractPersistableCustom<Long> {

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "journal_provenance_id", nullable = false)
    private HistoricalJournalProvenance journalProvenance;
    @Column(name = "source_line_id", nullable = false, length = 64)
    private String sourceLineId;
    @Column(name = "source_line_sequence", nullable = false)
    private Integer sourceLineSequence;
    @Column(name = "source_line_hash", nullable = false, length = 64)
    private String sourceLineHash;
    @Column(name = "source_account_id", nullable = false, length = 64)
    private String sourceAccountId;
    @Column(name = "source_account_code", nullable = false, length = 64)
    private String sourceAccountCode;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "target_gl_account_id", nullable = false)
    private GLAccount targetGlAccount;
    @Column(name = "source_debit_amount", precision = 18, scale = 2)
    private BigDecimal sourceDebitAmount;
    @Column(name = "source_credit_amount", precision = 18, scale = 2)
    private BigDecimal sourceCreditAmount;
    @Column(name = "source_side", nullable = false, length = 8)
    private String sourceSide;
    @Column(name = "source_amount", nullable = false, precision = 18, scale = 2)
    private BigDecimal sourceAmount;
    @Column(name = "target_side", nullable = false, length = 8)
    private String targetSide;
    @Column(name = "target_type_enum", nullable = false)
    private Integer targetTypeEnum;
    @Column(name = "target_amount", nullable = false, precision = 19, scale = 6)
    private BigDecimal targetAmount;
    @Column(name = "target_entry_date", nullable = false)
    private LocalDate targetEntryDate;
    @Column(name = "source_movement_reference", length = 128)
    private String sourceMovementReference;
    @Column(name = "source_document_reference", length = 128)
    private String sourceDocumentReference;
    @Column(name = "source_destination_branch_id", nullable = false, length = 32)
    private String sourceDestinationBranchId;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "target_office_id", nullable = false)
    private Office targetOffice;
    @Column(name = "target_office_external_id", nullable = false, length = 100)
    private String targetOfficeExternalId;
    @Column(name = "target_dimensions", nullable = false, columnDefinition = "TEXT")
    private String targetDimensions;
    @Column(name = "source_line_concept", columnDefinition = "TEXT")
    private String sourceLineConcept;
    @Column(name = "source_line_concept_sha256", nullable = false, length = 64)
    private String sourceLineConceptSha256;
    @Column(name = "source_line_aux_concept", columnDefinition = "TEXT")
    private String sourceLineAuxConcept;
    @Column(name = "source_line_aux_concept_sha256", nullable = false, length = 64)
    private String sourceLineAuxConceptSha256;
    @Column(name = "target_description_sha256", nullable = false, length = 64)
    private String targetDescriptionSha256;
    @Column(name = "description_truncated", nullable = false)
    private boolean descriptionTruncated;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "target_journal_entry_id")
    private JournalEntry targetJournalEntry;
    @Column(name = "result", nullable = false, length = 32)
    private String result;
    @Column(name = "reason_code", length = 128)
    private String reasonCode;
    @Column(name = "known_transferred_loan_office_mismatch", nullable = false)
    private boolean knownTransferredLoanOfficeMismatch;
    @Column(name = "known_anomaly_codes", columnDefinition = "TEXT")
    private String knownAnomalyCodes;
    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;

    static HistoricalJournalLineProvenance reserve(HistoricalJournalProvenance header,
            HistoricalJournalImportRequest.HistoricalJournalLineImportRequest request, GLAccount account, Office office, String dimensions,
            String side, Integer type, BigDecimal amount, LocalDate entryDate) {
        HistoricalJournalLineProvenance value = new HistoricalJournalLineProvenance();
        value.journalProvenance = header;
        value.sourceLineId = request.sourceLineId();
        value.sourceLineSequence = request.sourceLineSequence();
        value.sourceLineHash = request.sourceLineHash();
        value.sourceAccountId = request.sourceAccountId();
        value.sourceAccountCode = request.sourceAccountCode();
        value.targetGlAccount = account;
        value.sourceDebitAmount = request.debit();
        value.sourceCreditAmount = request.credit();
        value.sourceSide = side;
        value.sourceAmount = amount;
        value.targetSide = side;
        value.targetTypeEnum = type;
        value.targetAmount = amount.setScale(6);
        value.targetEntryDate = entryDate;
        value.sourceMovementReference = request.sourceMovementReference();
        value.sourceDocumentReference = request.sourceDocumentReference();
        value.sourceDestinationBranchId = request.sourceDestinationBranchId();
        value.targetOffice = office;
        value.targetOfficeExternalId = request.officeExternalId();
        value.targetDimensions = dimensions;
        value.sourceLineConcept = request.sourceLineConcept();
        value.sourceLineConceptSha256 = request.sourceLineConceptSha256();
        value.sourceLineAuxConcept = request.sourceLineAuxConcept();
        value.sourceLineAuxConceptSha256 = request.sourceLineAuxConceptSha256();
        value.targetDescriptionSha256 = request.descriptionSha256();
        value.descriptionTruncated = Boolean.TRUE.equals(request.descriptionTruncated());
        value.result = "RESERVED";
        value.knownTransferredLoanOfficeMismatch = Boolean.TRUE.equals(request.knownTransferredLoanOfficeMismatch());
        value.knownAnomalyCodes = request.knownAnomalyCodes();
        value.createdAt = DateUtils.getAuditOffsetDateTime();
        return value;
    }

    void markImported(JournalEntry journalEntry) {
        if (!"RESERVED".equals(result) || targetJournalEntry != null) {
            throw new HistoricalJournalImportException("provenance.immutable", "Successful historical journal provenance is immutable");
        }
        this.targetJournalEntry = journalEntry;
        this.result = "IMPORTED";
    }
}
