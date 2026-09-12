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
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.service.DateUtils;

@Entity
@Table(name = "credesal_arissto_gl_journal")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class HistoricalJournalProvenance extends AbstractPersistableCustom<Long> {

    @Column(name = "provenance_schema_version", nullable = false, length = 32)
    private String provenanceSchemaVersion;
    @Column(name = "source_system", nullable = false, length = 32)
    private String sourceSystem;
    @Column(name = "source_company_id", nullable = false, length = 32)
    private String sourceCompanyId;
    @Column(name = "source_branch_id", nullable = false, length = 32)
    private String sourceBranchId;
    @Column(name = "source_period_id", nullable = false, length = 32)
    private String sourcePeriodId;
    @Column(name = "source_journal_id", nullable = false, length = 64)
    private String sourceJournalId;
    @Column(name = "source_journal_number", nullable = false, length = 64)
    private String sourceJournalNumber;
    @Column(name = "source_journal_date", nullable = false)
    private LocalDate sourceJournalDate;
    @Column(name = "source_journal_type", nullable = false, length = 32)
    private String sourceJournalType;
    @Column(name = "source_module_code", length = 32)
    private String sourceModuleCode;
    @Column(name = "source_status", nullable = false, length = 16)
    private String sourceStatus;
    @Column(name = "source_liquidation_flag", length = 8)
    private String sourceLiquidationFlag;
    @Column(name = "source_opening_flag", length = 8)
    private String sourceOpeningFlag;
    @Column(name = "source_header_concept", columnDefinition = "TEXT")
    private String sourceHeaderConcept;
    @Column(name = "source_header_concept_sha256", nullable = false, length = 64)
    private String sourceHeaderConceptSha256;
    @Column(name = "source_header_description", columnDefinition = "TEXT")
    private String sourceHeaderDescription;
    @Column(name = "source_header_description_sha256", nullable = false, length = 64)
    private String sourceHeaderDescriptionSha256;
    @Column(name = "source_hash", nullable = false, length = 64)
    private String sourceHash;
    @Column(name = "planned_hash", nullable = false, length = 64)
    private String plannedHash;
    @Column(name = "contract_hash", nullable = false, length = 64)
    private String contractHash;
    @Column(name = "source_schema_signature", nullable = false, length = 64)
    private String sourceSchemaSignature;
    @Column(name = "coa_mapping_version", nullable = false, length = 64)
    private String coaMappingVersion;
    @Column(name = "coa_mapping_hash", nullable = false, length = 64)
    private String coaMappingHash;
    @Column(name = "office_mapping_version", nullable = false, length = 64)
    private String officeMappingVersion;
    @Column(name = "office_mapping_hash", nullable = false, length = 64)
    private String officeMappingHash;
    @Column(name = "policy_version", nullable = false, length = 64)
    private String policyVersion;
    @Column(name = "policy_hash", nullable = false, length = 64)
    private String policyHash;
    @Column(name = "description_policy_version", nullable = false, length = 64)
    private String descriptionPolicyVersion;
    @Column(name = "source_fingerprint", nullable = false, length = 128)
    private String sourceFingerprint;
    @Column(name = "target_fingerprint", nullable = false, length = 128)
    private String targetFingerprint;
    @Column(name = "target_baseline_hash", nullable = false, length = 64)
    private String targetBaselineHash;
    @Column(name = "cutoff_date", nullable = false)
    private LocalDate cutoffDate;
    @Column(name = "cutoff_timezone_id", nullable = false, length = 64)
    private String cutoffTimezoneId;
    @Column(name = "cutoff_configuration_revision", nullable = false)
    private Long cutoffConfigurationRevision;
    @Column(name = "cutoff_configuration_hash", nullable = false, length = 64)
    private String cutoffConfigurationHash;
    @Column(name = "plan_id", nullable = false, length = 64)
    private String planId;
    @Column(name = "run_id", length = 64)
    private String runId;
    @Column(name = "target_transaction_id", length = 50)
    private String targetTransactionId;
    @Column(name = "target_ref_num", length = 100)
    private String targetRefNum;
    @Column(name = "result", nullable = false, length = 32)
    private String result;
    @Column(name = "reason_code", length = 128)
    private String reasonCode;
    @Column(name = "known_transferred_loan_office_mismatch", nullable = false)
    private boolean knownTransferredLoanOfficeMismatch;
    @Column(name = "known_anomaly_codes", columnDefinition = "TEXT")
    private String knownAnomalyCodes;
    @Column(name = "retry_count", nullable = false)
    private int retryCount;
    @Column(name = "last_retry_at")
    private OffsetDateTime lastRetryAt;
    @Column(name = "applied_at")
    private OffsetDateTime appliedAt;
    @Column(name = "reconciled_at")
    private OffsetDateTime reconciledAt;
    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;
    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    static HistoricalJournalProvenance reserve(HistoricalJournalImportRequest request) {
        HistoricalJournalProvenance value = new HistoricalJournalProvenance();
        value.provenanceSchemaVersion = request.provenanceSchemaVersion();
        value.sourceSystem = request.sourceSystem();
        value.sourceCompanyId = request.sourceCompanyId();
        value.sourceBranchId = request.sourceBranchId();
        value.sourcePeriodId = request.sourcePeriodId();
        value.sourceJournalId = request.sourceJournalId();
        value.sourceJournalNumber = request.sourceJournalNumber();
        value.sourceJournalDate = request.entryDate();
        value.sourceJournalType = request.sourceJournalType();
        value.sourceModuleCode = request.sourceModuleCode();
        value.sourceStatus = request.sourceStatus();
        value.sourceLiquidationFlag = request.sourceLiquidationFlag();
        value.sourceOpeningFlag = request.sourceOpeningFlag();
        value.sourceHeaderConcept = request.sourceHeaderConcept();
        value.sourceHeaderConceptSha256 = request.sourceHeaderConceptSha256();
        value.sourceHeaderDescription = request.sourceHeaderDescription();
        value.sourceHeaderDescriptionSha256 = request.sourceHeaderDescriptionSha256();
        value.sourceHash = request.sourceHash();
        value.plannedHash = request.plannedHash();
        value.contractHash = request.contractHash();
        value.sourceSchemaSignature = request.sourceSchemaSignature();
        value.coaMappingVersion = request.coaMappingVersion();
        value.coaMappingHash = request.coaMappingHash();
        value.officeMappingVersion = request.officeMappingVersion();
        value.officeMappingHash = request.officeMappingHash();
        value.policyVersion = request.policyVersion();
        value.policyHash = request.policyHash();
        value.descriptionPolicyVersion = request.descriptionPolicyVersion();
        value.sourceFingerprint = request.sourceFingerprint();
        value.targetFingerprint = request.targetFingerprint();
        value.targetBaselineHash = request.targetBaselineHash();
        value.cutoffDate = request.cutoffDate();
        value.cutoffTimezoneId = request.cutoffTimezoneId();
        value.cutoffConfigurationRevision = request.cutoffConfigurationRevision();
        value.cutoffConfigurationHash = request.cutoffConfigurationHash();
        value.planId = request.planId();
        value.runId = request.runId();
        value.result = "RESERVED";
        value.knownTransferredLoanOfficeMismatch = Boolean.TRUE.equals(request.knownTransferredLoanOfficeMismatch());
        value.knownAnomalyCodes = request.knownAnomalyCodes();
        value.createdAt = DateUtils.getAuditOffsetDateTime();
        return value;
    }

    void markImported(String transactionId, String referenceNumber) {
        if (!"RESERVED".equals(result)) {
            throw new HistoricalJournalImportException("provenance.immutable", "Successful historical journal provenance is immutable");
        }
        this.targetTransactionId = transactionId;
        this.targetRefNum = referenceNumber;
        this.result = "IMPORTED";
        this.appliedAt = DateUtils.getAuditOffsetDateTime();
        this.updatedAt = this.appliedAt;
    }

    boolean isImported() {
        return "IMPORTED".equals(result);
    }
}
