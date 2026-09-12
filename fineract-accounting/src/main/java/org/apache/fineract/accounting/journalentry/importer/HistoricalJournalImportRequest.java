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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

public record HistoricalJournalImportRequest(String provenanceSchemaVersion, String sourceSystem, String sourceCompanyId,
        String sourceBranchId, String sourcePeriodId, String sourceJournalId, String sourceJournalNumber, LocalDate entryDate,
        String sourceJournalType, String sourceModuleCode, String sourceStatus, String sourceLiquidationFlag, String sourceOpeningFlag,
        String sourceHeaderConcept, String sourceHeaderConceptSha256, String sourceHeaderDescription, String sourceHeaderDescriptionSha256,
        String sourceHash, String plannedHash, String contractHash, String sourceSchemaSignature, String coaMappingVersion,
        String coaMappingHash, String officeMappingVersion, String officeMappingHash, String policyVersion, String policyHash,
        String descriptionPolicyVersion, String sourceFingerprint, String targetFingerprint, String targetBaselineHash,
        LocalDate cutoffDate, String cutoffTimezoneId, Long cutoffConfigurationRevision, String cutoffConfigurationHash, String planId,
        String runId, String refNum, String currency, BigDecimal debitTotal, BigDecimal creditTotal,
        Boolean knownTransferredLoanOfficeMismatch, String knownAnomalyCodes, List<HistoricalJournalLineImportRequest> lines) {

    public record HistoricalJournalLineImportRequest(String sourceLineId, Integer sourceLineSequence, String sourceLineHash,
            String sourceAccountId, String sourceAccountCode, String targetAccountCode, Long targetGlAccountId, BigDecimal debit,
            BigDecimal credit, String sourceMovementReference, String sourceDocumentReference, String sourceDestinationBranchId,
            Long officeId, String officeExternalId, Map<String, String> dimensions, String sourceLineConcept,
            String sourceLineConceptSha256, String sourceLineAuxConcept, String sourceLineAuxConceptSha256, String description,
            String descriptionSha256, Boolean descriptionTruncated, Boolean knownTransferredLoanOfficeMismatch, String knownAnomalyCodes) {
    }
}
