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
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.accounting.closure.domain.GLClosure;
import org.apache.fineract.accounting.closure.domain.GLClosureRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfiguration;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfigurationRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffLifecycleState;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.cutoff.AccountingPostingOrigin;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.domain.JournalEntryType;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.OrganisationCurrency;
import org.apache.fineract.organisation.monetary.domain.OrganisationCurrencyRepositoryWrapper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepository;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class HistoricalJournalImportServiceImpl implements HistoricalJournalImportService {

    static final String TIMEZONE = "America/El_Salvador";
    static final String SOURCE_SYSTEM = "ARISSTO";
    static final String PROVENANCE_SCHEMA_VERSION = "arissto-gl-v1";

    private final PlatformSecurityContext securityContext;
    private final AccountingPostingContext postingContext;
    private final AccountingCutoffConfigurationRepository cutoffRepository;
    private final AccountingCutoffPolicyService cutoffPolicyService;
    private final HistoricalJournalProvenanceRepository provenanceRepository;
    private final HistoricalJournalLineProvenanceRepository lineProvenanceRepository;
    private final GLAccountRepository glAccountRepository;
    private final OfficeRepository officeRepository;
    private final GLClosureRepository closureRepository;
    private final OrganisationCurrencyRepositoryWrapper currencyRepository;
    private final JournalEntryPersistenceService journalEntryPersistenceService;

    @Override
    @Transactional
    public HistoricalJournalImportResult importJournal(HistoricalJournalImportRequest request) {
        AppUser user = securityContext.authenticatedUser();
        user.validateHasPermissionTo(IMPORT_PERMISSION);
        requireRequestShape(request);

        AccountingCutoffConfiguration cutoff = cutoffRepository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID)
                .orElseThrow(() -> failure("cutoff.not.configured", "The tenant accounting cutoff is not configured"));
        validateCutoff(request, cutoff);
        HistoricalJournalProvenance existing = findExisting(request);
        if (existing != null) {
            return existingResult(request, existing);
        }

        OrganisationCurrency currency = currencyRepository.findOneWithNotFoundDetection(request.currency());
        if (!"USD".equals(request.currency()) || currency.toMonetaryCurrency().getDigitsAfterDecimal() != 2) {
            throw failure("currency.unsupported", "Historical journal import requires the enabled two-decimal USD currency");
        }

        List<ValidatedLine> validatedLines = validateLines(request, user);
        String transactionId = transactionId(request);
        HistoricalJournalProvenance provenance = provenanceRepository.saveAndFlush(HistoricalJournalProvenance.reserve(request));
        List<Long> journalEntryIds = postingContext.executeAs(AccountingPostingOrigin.ARISSTO_HISTORICAL_GL_IMPORT,
                () -> persistLines(request, provenance, validatedLines, transactionId));
        provenance.markImported(transactionId, request.refNum());
        provenanceRepository.saveAndFlush(provenance);
        return new HistoricalJournalImportResult(sourceKey(request), transactionId, List.copyOf(journalEntryIds), false);
    }

    @Override
    @Transactional(readOnly = true)
    public HistoricalJournalProvenanceData retrieve(String companyId, String branchId, String periodId, String journalId) {
        securityContext.authenticatedUser().validateHasPermissionTo(READ_PROVENANCE_PERMISSION);
        HistoricalJournalProvenance header = provenanceRepository
                .findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(SOURCE_SYSTEM, companyId,
                        branchId, periodId, journalId)
                .orElseThrow(() -> failure("provenance.not.found", "Historical journal provenance was not found"));
        List<HistoricalJournalProvenanceData.HistoricalJournalLineProvenanceData> lines = lineProvenanceRepository
                .findByJournalProvenanceIdOrderBySourceLineSequenceAsc(header.getId()).stream()
                .map(line -> new HistoricalJournalProvenanceData.HistoricalJournalLineProvenanceData(line.getSourceLineId(),
                        line.getSourceLineConcept(), line.getSourceLineAuxConcept(),
                        line.getTargetJournalEntry() == null ? null : line.getTargetJournalEntry().getId()))
                .toList();
        return new HistoricalJournalProvenanceData(sourceKey(header), header.getTargetTransactionId(), header.getSourceHeaderConcept(),
                header.getSourceHeaderDescription(), lines);
    }

    private List<Long> persistLines(HistoricalJournalImportRequest request, HistoricalJournalProvenance provenance,
            List<ValidatedLine> lines, String transactionId) {
        List<Long> ids = new ArrayList<>(lines.size());
        for (ValidatedLine line : lines) {
            HistoricalJournalLineProvenance lineProvenance = lineProvenanceRepository
                    .saveAndFlush(HistoricalJournalLineProvenance.reserve(provenance, line.request(), line.account(), line.office(),
                            line.dimensions(), line.side().name(), line.side().getValue(), line.amount(), request.entryDate()));
            JournalEntry journalEntry = JournalEntry.createNew(line.office(), null, line.account(), request.currency(), transactionId, true,
                    request.entryDate(), line.side(), line.amount().setScale(6, RoundingMode.UNNECESSARY), line.request().description(),
                    null, null, request.refNum(), null, null, null, null, line.dimensions());
            cutoffPolicyService.assertJournalPersistenceAllowed(request.entryDate());
            JournalEntry saved = journalEntryPersistenceService.saveAndFlush(journalEntry);
            lineProvenance.markImported(saved);
            lineProvenanceRepository.saveAndFlush(lineProvenance);
            ids.add(saved.getId());
        }
        return ids;
    }

    private List<ValidatedLine> validateLines(HistoricalJournalImportRequest request, AppUser user) {
        Set<String> lineIds = new HashSet<>();
        Set<Integer> sequences = new HashSet<>();
        Map<Long, Office> offices = new LinkedHashMap<>();
        BigDecimal debits = BigDecimal.ZERO;
        BigDecimal credits = BigDecimal.ZERO;
        List<ValidatedLine> result = new ArrayList<>(request.lines().size());
        for (HistoricalJournalImportRequest.HistoricalJournalLineImportRequest line : request.lines()) {
            if (line == null) {
                throw failure("journal.partial", "Historical journal lines may not be null");
            }
            requireText(line.sourceLineId(), "source.line.id.required");
            requireHash(line.sourceLineHash(), "source.line.hash.invalid");
            requireText(line.sourceAccountId(), "source.account.id.required");
            requireText(line.sourceAccountCode(), "source.account.code.required");
            requireText(line.targetAccountCode(), "target.account.code.required");
            if (!lineIds.add(line.sourceLineId()) || line.sourceLineSequence() == null || line.sourceLineSequence() < 1
                    || !sequences.add(line.sourceLineSequence())) {
                throw failure("source.line.duplicate", "Historical journal line identities and sequences must be complete and unique");
            }
            BigDecimal debit = amount(line.debit());
            BigDecimal credit = amount(line.credit());
            boolean isDebit = debit.signum() > 0 && credit.signum() == 0;
            boolean isCredit = credit.signum() > 0 && debit.signum() == 0;
            if (!isDebit && !isCredit) {
                throw failure("line.side.invalid", "Each historical journal line must contain exactly one positive debit or credit");
            }
            JournalEntryType side = isDebit ? JournalEntryType.DEBIT : JournalEntryType.CREDIT;
            BigDecimal value = isDebit ? debit : credit;
            debits = debits.add(debit);
            credits = credits.add(credit);

            if (line.targetGlAccountId() == null) {
                throw failure("account.not.found", "A target GL account identifier is required");
            }
            GLAccount account = glAccountRepository.findById(line.targetGlAccountId())
                    .orElseThrow(() -> failure("account.not.found", "A target GL account was not found"));
            if (!Objects.equals(account.getGlCode(), line.targetAccountCode())) {
                throw failure("account.mapping.drift", "A target GL account no longer matches the planned target account code");
            }
            if (account.isDisabled() || !account.isManualEntriesAllowed()) {
                throw failure("account.not.postable", "A target GL account does not permit historical manual posting");
            }

            if (line.officeId() == null) {
                throw failure("office.not.found", "A target office identifier is required");
            }
            Office office = officeRepository.findById(line.officeId())
                    .orElseThrow(() -> failure("office.not.found", "A target office was not found"));
            String externalId = office.getExternalId() == null ? null : office.getExternalId().getValue();
            if (!Objects.equals(externalId, line.officeExternalId()) || line.dimensions() == null || line.dimensions().size() != 1
                    || !Objects.equals(externalId, line.dimensions().get("office"))) {
                throw failure("office.dimension.drift", "The line office and canonical office dimension do not agree");
            }
            if (!user.hasAccessToOffice(office)) {
                throw failure("office.unauthorized", "The authenticated user does not have access to every journal office");
            }
            offices.put(office.getId(), office);
            validateTextHashes(line);
            result.add(new ValidatedLine(line, account, office, canonicalDimensions(externalId), side, value));
        }
        if (debits.compareTo(credits) != 0 || debits.signum() <= 0 || debits.compareTo(amount(request.debitTotal())) != 0
                || credits.compareTo(amount(request.creditTotal())) != 0) {
            throw failure("journal.unbalanced", "Historical journal debit and credit totals must match exactly");
        }
        for (Office office : offices.values()) {
            GLClosure closure = closureRepository.getLatestActiveGLClosureByBranch(office.getId());
            if (closure != null && !request.entryDate().isAfter(closure.getClosingDate())) {
                throw failure("office.closure.conflict", "The journal date is not after every involved office closure");
            }
        }
        return result;
    }

    private void validateCutoff(HistoricalJournalImportRequest request, AccountingCutoffConfiguration cutoff) {
        if (cutoff.getLifecycleState() != AccountingCutoffLifecycleState.ACTIVE
                || !Objects.equals(cutoff.getCutoffDate(), request.cutoffDate())
                || !Objects.equals(cutoff.getTimezoneId(), request.cutoffTimezoneId()) || !TIMEZONE.equals(request.cutoffTimezoneId())
                || cutoff.getConfigurationRevision() != request.cutoffConfigurationRevision()
                || !Objects.equals(cutoff.getConfigurationHash(), request.cutoffConfigurationHash())) {
            throw failure("cutoff.binding.drift", "The request does not match the active tenant cutoff configuration");
        }
        if (!request.entryDate().isBefore(cutoff.getCutoffDate())) {
            throw failure("cutoff.violation", "Historical journal date must be strictly before the accounting cutoff");
        }
        if (!"3".equals(request.sourceStatus())) {
            throw failure("source.status.invalid", "Only populated and balanced source status 3 journals may be imported");
        }
    }

    private void requireRequestShape(HistoricalJournalImportRequest request) {
        if (request == null) {
            throw failure("request.required", "A complete historical journal request is required");
        }
        requireEquals(PROVENANCE_SCHEMA_VERSION, request.provenanceSchemaVersion(), "provenance.schema.invalid");
        requireEquals(SOURCE_SYSTEM, request.sourceSystem(), "source.system.invalid");
        requireText(request.sourceCompanyId(), "source.company.required");
        requireText(request.sourceBranchId(), "source.branch.required");
        requireText(request.sourcePeriodId(), "source.period.required");
        requireText(request.sourceJournalId(), "source.journal.required");
        requireText(request.sourceJournalNumber(), "source.journal.number.required");
        requireText(request.sourceJournalType(), "source.journal.type.required");
        requireText(request.sourceStatus(), "source.status.required");
        requireText(request.planId(), "plan.id.required");
        requireText(request.refNum(), "reference.required");
        requireEquals(request.sourceJournalNumber(), request.refNum(), "reference.mismatch");
        if (request.sourceJournalDate() == null || request.entryDate() == null || request.cutoffDate() == null
                || request.cutoffConfigurationRevision() == null) {
            throw failure("dates.required", "Source, effective and cutoff dates and the cutoff revision are required");
        }
        String[] hashes = { request.sourceHash(), request.plannedHash(), request.contractHash(), request.sourceSchemaSignature(),
                request.coaMappingHash(), request.officeMappingHash(), request.policyHash(), request.targetBaselineHash(),
                request.cutoffConfigurationHash() };
        for (String hash : hashes) {
            requireHash(hash, "binding.hash.invalid");
        }
        requireText(request.coaMappingVersion(), "coa.mapping.version.required");
        requireText(request.officeMappingVersion(), "office.mapping.version.required");
        requireText(request.policyVersion(), "policy.version.required");
        requireText(request.descriptionPolicyVersion(), "description.policy.version.required");
        requireText(request.sourceFingerprint(), "source.fingerprint.required");
        requireText(request.targetFingerprint(), "target.fingerprint.required");
        if (request.lines() == null || request.lines().size() < 2) {
            throw failure("journal.partial", "A complete journal requires at least two lines");
        }
        requireFieldHash("CNT_PARTIDAS.CONCEPTO", request.sourceHeaderConcept(), request.sourceHeaderConceptSha256());
        requireFieldHash("CNT_PARTIDAS.DESCRIPCION", request.sourceHeaderDescription(), request.sourceHeaderDescriptionSha256());
    }

    private HistoricalJournalProvenance findExisting(HistoricalJournalImportRequest request) {
        return provenanceRepository
                .findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(request.sourceSystem(),
                        request.sourceCompanyId(), request.sourceBranchId(), request.sourcePeriodId(), request.sourceJournalId())
                .orElse(null);
    }

    private HistoricalJournalImportResult existingResult(HistoricalJournalImportRequest request, HistoricalJournalProvenance existing) {
        if (!existing.isImported() || !Objects.equals(existing.getSourceHash(), request.sourceHash())
                || !Objects.equals(existing.getPlannedHash(), request.plannedHash())) {
            throw failure("source.key.conflict", "The source journal key is already reserved with different or incomplete content");
        }
        List<Long> ids = lineProvenanceRepository.findByJournalProvenanceIdOrderBySourceLineSequenceAsc(existing.getId()).stream()
                .map(HistoricalJournalLineProvenance::getTargetJournalEntry).filter(Objects::nonNull).map(JournalEntry::getId).toList();
        if (ids.size() != request.lines().size()) {
            throw failure("prior.success.incomplete", "Prior success does not contain the complete target line set");
        }
        return new HistoricalJournalImportResult(sourceKey(request), existing.getTargetTransactionId(), ids, true);
    }

    private void validateTextHashes(HistoricalJournalImportRequest.HistoricalJournalLineImportRequest line) {
        requireFieldHash("CNT_DETALLE_PARTIDAS.CONCEPTO", line.sourceLineConcept(), line.sourceLineConceptSha256());
        requireFieldHash("CNT_DETALLE_PARTIDAS.CONCEPTO_AUX", line.sourceLineAuxConcept(), line.sourceLineAuxConceptSha256());
        requireFieldHash("acc_gl_journal_entry.description", line.description(), line.descriptionSha256());
        if (line.description() != null && line.description().length() > 500) {
            throw failure("description.too.long", "The native journal description exceeds 500 characters");
        }
    }

    private BigDecimal amount(BigDecimal value) {
        BigDecimal normalized = value == null ? BigDecimal.ZERO.setScale(2) : value;
        if (normalized.signum() < 0 || normalized.scale() > 2 || normalized.precision() - normalized.scale() > 13) {
            throw failure("amount.invalid", "Historical journal amounts must be non-negative exact cents within target precision");
        }
        return normalized.setScale(2, RoundingMode.UNNECESSARY);
    }

    private void requireFieldHash(String field, String value, String actual) {
        requireHash(actual, "text.hash.invalid");
        String marker = value == null ? "<NULL>" : value;
        if (!sha256(field + "\0" + marker).equals(actual)) {
            throw failure("text.hash.mismatch", "A restricted legacy text value does not match its declared hash");
        }
    }

    private void requireHash(String value, String reason) {
        if (value == null || !value.matches("[0-9a-f]{64}")) {
            throw failure(reason, "A required SHA-256 binding is missing or invalid");
        }
    }

    private void requireText(String value, String reason) {
        if (value == null || value.isBlank()) {
            throw failure(reason, "A required historical journal field is missing");
        }
    }

    private void requireEquals(String expected, String actual, String reason) {
        if (!Objects.equals(expected, actual)) {
            throw failure(reason, "A historical journal contract value does not match");
        }
    }

    private String transactionId(HistoricalJournalImportRequest request) {
        return "AI" + sha256(sourceKey(request)).substring(0, 48);
    }

    private String sourceKey(HistoricalJournalImportRequest request) {
        return String.join(":", request.sourceCompanyId(), request.sourceBranchId(), request.sourcePeriodId(), request.sourceJournalId());
    }

    private String sourceKey(HistoricalJournalProvenance header) {
        return String.join(":", header.getSourceCompanyId(), header.getSourceBranchId(), header.getSourcePeriodId(),
                header.getSourceJournalId());
    }

    private String canonicalDimensions(String officeExternalId) {
        return "{\"office\":\"" + officeExternalId.replace("\\", "\\\\").replace("\"", "\\\"") + "\"}";
    }

    private String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required for historical journal import", exception);
        }
    }

    private HistoricalJournalImportException failure(String reason, String message) {
        return new HistoricalJournalImportException(reason, message);
    }

    private record ValidatedLine(HistoricalJournalImportRequest.HistoricalJournalLineImportRequest request, GLAccount account,
            Office office, String dimensions, JournalEntryType side, BigDecimal amount) {
    }
}
