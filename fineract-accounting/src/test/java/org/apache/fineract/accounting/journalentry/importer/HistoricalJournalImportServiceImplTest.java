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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.persistence.LockModeType;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.fineract.accounting.closure.domain.GLClosure;
import org.apache.fineract.accounting.closure.domain.GLClosureRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfiguration;
import org.apache.fineract.accounting.cutoff.AccountingCutoffConfigurationRepository;
import org.apache.fineract.accounting.cutoff.AccountingCutoffLifecycleState;
import org.apache.fineract.accounting.cutoff.AccountingCutoffPolicyService;
import org.apache.fineract.accounting.cutoff.AccountingPostingContext;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.journalentry.domain.JournalEntry;
import org.apache.fineract.accounting.journalentry.service.JournalEntryPersistenceService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.security.exception.NoAuthorizationException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.organisation.monetary.domain.OrganisationCurrency;
import org.apache.fineract.organisation.monetary.domain.OrganisationCurrencyRepositoryWrapper;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepository;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.transaction.annotation.Transactional;

class HistoricalJournalImportServiceImplTest {

    private static final LocalDate ENTRY_DATE = LocalDate.of(2025, 12, 15);
    private static final LocalDate CUTOFF_DATE = LocalDate.of(2026, 1, 1);
    private static final String HASH = "a".repeat(64);

    private final PlatformSecurityContext securityContext = mock(PlatformSecurityContext.class);
    private final AccountingPostingContext postingContext = new AccountingPostingContext();
    private final AccountingCutoffConfigurationRepository cutoffRepository = mock(AccountingCutoffConfigurationRepository.class);
    private final AccountingCutoffPolicyService cutoffPolicyService = mock(AccountingCutoffPolicyService.class);
    private final HistoricalJournalProvenanceRepository provenanceRepository = mock(HistoricalJournalProvenanceRepository.class);
    private final HistoricalJournalLineProvenanceRepository lineProvenanceRepository = mock(
            HistoricalJournalLineProvenanceRepository.class);
    private final GLAccountRepository glAccountRepository = mock(GLAccountRepository.class);
    private final OfficeRepository officeRepository = mock(OfficeRepository.class);
    private final GLClosureRepository closureRepository = mock(GLClosureRepository.class);
    private final OrganisationCurrencyRepositoryWrapper currencyRepository = mock(OrganisationCurrencyRepositoryWrapper.class);
    private final JournalEntryPersistenceService journalEntryPersistenceService = mock(JournalEntryPersistenceService.class);
    private final AppUser user = mock(AppUser.class);
    private final AccountingCutoffConfiguration cutoff = mock(AccountingCutoffConfiguration.class);
    private final GLAccount account = mock(GLAccount.class);
    private final Office office1 = office(1L, "1");
    private final Office office2 = office(2L, "2");
    private final HistoricalJournalImportServiceImpl service = new HistoricalJournalImportServiceImpl(securityContext, postingContext,
            cutoffRepository, cutoffPolicyService, provenanceRepository, lineProvenanceRepository, glAccountRepository, officeRepository,
            closureRepository, currencyRepository, journalEntryPersistenceService);

    @BeforeEach
    void setUp() {
        ThreadLocalContextUtil.setBusinessDates(new HashMap<>(Map.of(BusinessDateType.BUSINESS_DATE, CUTOFF_DATE)));
        when(securityContext.authenticatedUser()).thenReturn(user);
        when(cutoffRepository.findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID)).thenReturn(Optional.of(cutoff));
        when(cutoff.getLifecycleState()).thenReturn(AccountingCutoffLifecycleState.ACTIVE);
        when(cutoff.getCutoffDate()).thenReturn(CUTOFF_DATE);
        when(cutoff.getTimezoneId()).thenReturn(HistoricalJournalImportServiceImpl.TIMEZONE);
        when(cutoff.getConfigurationRevision()).thenReturn(2L);
        when(cutoff.getConfigurationHash()).thenReturn(HASH);
        when(provenanceRepository.findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(any(), any(),
                any(), any(), any())).thenReturn(Optional.empty());
        when(glAccountRepository.findById(7L)).thenReturn(Optional.of(account));
        when(account.getGlCode()).thenReturn("1110010199");
        when(account.isManualEntriesAllowed()).thenReturn(true);
        when(officeRepository.findById(1L)).thenReturn(Optional.of(office1));
        when(officeRepository.findById(2L)).thenReturn(Optional.of(office2));
        when(user.hasAccessToOffice(any())).thenReturn(true);
        OrganisationCurrency currency = mock(OrganisationCurrency.class);
        when(currency.toMonetaryCurrency()).thenReturn(new MonetaryCurrency("USD", 2, null));
        when(currencyRepository.findOneWithNotFoundDetection("USD")).thenReturn(currency);
        AtomicLong provenanceIds = new AtomicLong(10);
        when(provenanceRepository.saveAndFlush(any())).thenAnswer(invocation -> {
            HistoricalJournalProvenance value = invocation.getArgument(0);
            if (value.getId() == null) {
                value.setId(provenanceIds.incrementAndGet());
            }
            return value;
        });
        when(lineProvenanceRepository.saveAndFlush(any())).thenAnswer(invocation -> invocation.getArgument(0));
        AtomicLong journalIds = new AtomicLong(100);
        when(journalEntryPersistenceService.saveAndFlush(any())).thenAnswer(invocation -> {
            JournalEntry value = invocation.getArgument(0);
            value.setId(journalIds.incrementAndGet());
            return value;
        });
    }

    @Test
    void importsBalancedMultiAgencyJournalWithPerLineOfficeAndOneTransaction() {
        HistoricalJournalImportResult result = service.importJournal(validRequest());

        assertThat(result.unchanged()).isFalse();
        assertThat(result.journalEntryIds()).hasSize(2);
        assertThat(result.transactionId()).hasSize(50);
        var captor = org.mockito.ArgumentCaptor.forClass(JournalEntry.class);
        verify(journalEntryPersistenceService, org.mockito.Mockito.times(2)).saveAndFlush(captor.capture());
        assertThat(captor.getAllValues()).extracting(entry -> entry.getOffice().getId()).containsExactly(1L, 2L);
        assertThat(captor.getAllValues()).extracting(JournalEntry::getTransactionId).containsOnly(result.transactionId());
        assertThat(captor.getAllValues()).allSatisfy(entry -> {
            assertThat(entry.isManualEntry()).isTrue();
            assertThat(entry.getLoanTransactionId()).isNull();
            assertThat(entry.getSavingsTransactionId()).isNull();
            assertThat(entry.getEntityId()).isNull();
        });
    }

    @Test
    void identicalRetryAndLostResponseReturnPriorSuccessWithoutNewWrites() {
        HistoricalJournalImportRequest request = validRequest();
        HistoricalJournalProvenance existing = mock(HistoricalJournalProvenance.class);
        when(existing.isImported()).thenReturn(true);
        when(existing.getId()).thenReturn(9L);
        when(existing.getSourceHash()).thenReturn(request.sourceHash());
        when(existing.getPlannedHash()).thenReturn(request.plannedHash());
        when(existing.getTargetTransactionId()).thenReturn("prior-transaction");
        when(provenanceRepository.findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(any(), any(),
                any(), any(), any())).thenReturn(Optional.of(existing));
        HistoricalJournalLineProvenance firstLine = importedLine(101L);
        HistoricalJournalLineProvenance secondLine = importedLine(102L);
        when(lineProvenanceRepository.findByJournalProvenanceIdOrderBySourceLineSequenceAsc(9L)).thenReturn(List.of(firstLine, secondLine));

        HistoricalJournalImportResult result = service.importJournal(request);

        assertThat(result.unchanged()).isTrue();
        assertThat(result.transactionId()).isEqualTo("prior-transaction");
        assertThat(result.journalEntryIds()).containsExactly(101L, 102L);
        verify(journalEntryPersistenceService, never()).saveAndFlush(any());
    }

    @Test
    void changedHashForExistingKeyIsRejected() {
        HistoricalJournalProvenance existing = mock(HistoricalJournalProvenance.class);
        when(existing.isImported()).thenReturn(true);
        when(existing.getSourceHash()).thenReturn("b".repeat(64));
        when(provenanceRepository.findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(any(), any(),
                any(), any(), any())).thenReturn(Optional.of(existing));

        assertThatThrownBy(() -> service.importJournal(validRequest())).isInstanceOf(HistoricalJournalImportException.class)
                .hasMessageContaining("already reserved");
        verify(journalEntryPersistenceService, never()).saveAndFlush(any());
    }

    @Test
    void cutoffViolationIsRejectedBeforeAnyWrite() {
        HistoricalJournalImportRequest request = request(lines(), CUTOFF_DATE, CUTOFF_DATE);

        assertThatThrownBy(() -> service.importJournal(request)).isInstanceOf(HistoricalJournalImportException.class)
                .hasMessageContaining("strictly before");
        verify(provenanceRepository, never()).saveAndFlush(any());
    }

    @Test
    void closureConflictIsRejectedBeforeAnyWrite() {
        GLClosure closure = mock(GLClosure.class);
        when(closure.getClosingDate()).thenReturn(ENTRY_DATE);
        when(closureRepository.getLatestActiveGLClosureByBranch(1L)).thenReturn(closure);

        assertThatThrownBy(() -> service.importJournal(validRequest())).isInstanceOf(HistoricalJournalImportException.class)
                .hasMessageContaining("closure");
        verify(provenanceRepository, never()).saveAndFlush(any());
    }

    @Test
    void lineDimensionMustTakeCanonicalOfficeValue() {
        List<HistoricalJournalImportRequest.HistoricalJournalLineImportRequest> values = List.of(
                line("1", 1, 1L, "1", "10.00", "0.00", Map.of("office", "2")),
                line("2", 2, 2L, "2", "0.00", "10.00", Map.of("office", "2")));

        assertThatThrownBy(() -> service.importJournal(request(values, ENTRY_DATE, CUTOFF_DATE)))
                .isInstanceOf(HistoricalJournalImportException.class).hasMessageContaining("dimension");
    }

    @Test
    void officeAuthorizationIsCheckedForEveryLineBeforeAnyWrite() {
        when(user.hasAccessToOffice(office2)).thenReturn(false);

        assertThatThrownBy(() -> service.importJournal(validRequest())).isInstanceOf(HistoricalJournalImportException.class)
                .hasMessageContaining("does not have access");
        verify(provenanceRepository, never()).saveAndFlush(any());
    }

    @Test
    void dedicatedPermissionIsRequired() {
        doThrow(new NoAuthorizationException("denied")).when(user)
                .validateHasPermissionTo(HistoricalJournalImportService.IMPORT_PERMISSION);

        assertThatThrownBy(() -> service.importJournal(validRequest())).isInstanceOf(NoAuthorizationException.class);
        verify(cutoffRepository, never()).findByIdForUpdate(any());
    }

    @Test
    void losslessProvenanceReadRequiresItsSeparatePermission() {
        doThrow(new NoAuthorizationException("denied")).when(user)
                .validateHasPermissionTo(HistoricalJournalImportService.READ_PROVENANCE_PERMISSION);

        assertThatThrownBy(() -> service.retrieve("001", "001", "00065", "10")).isInstanceOf(NoAuthorizationException.class);
        verify(provenanceRepository, never()).findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(
                any(), any(), any(), any(), any());
    }

    @Test
    void laterLineFailureLeavesTheMethodExceptionalForTransactionRollback() throws NoSuchMethodException {
        JournalEntry first = journalEntry(101L);
        doReturn(first).doThrow(new IllegalStateException("second line failed")).when(journalEntryPersistenceService).saveAndFlush(any());

        assertThatThrownBy(() -> service.importJournal(validRequest())).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("second line failed");
        Transactional transactional = HistoricalJournalImportServiceImpl.class
                .getMethod("importJournal", HistoricalJournalImportRequest.class).getAnnotation(Transactional.class);
        assertThat(transactional).isNotNull();
    }

    @Test
    void cutoffRowPessimisticLockSerializesConcurrentDuplicateChecks() throws NoSuchMethodException {
        Lock lock = AccountingCutoffConfigurationRepository.class.getMethod("findByIdForUpdate", Long.class).getAnnotation(Lock.class);
        assertThat(lock).isNotNull();
        assertThat(lock.value()).isEqualTo(LockModeType.PESSIMISTIC_WRITE);

        service.importJournal(validRequest());
        InOrder order = inOrder(cutoffRepository, provenanceRepository);
        order.verify(cutoffRepository).findByIdForUpdate(AccountingCutoffConfiguration.SINGLETON_ID);
        order.verify(provenanceRepository).findBySourceSystemAndSourceCompanyIdAndSourceBranchIdAndSourcePeriodIdAndSourceJournalId(any(),
                any(), any(), any(), any());
    }

    private HistoricalJournalImportRequest validRequest() {
        return request(lines(), ENTRY_DATE, CUTOFF_DATE);
    }

    private List<HistoricalJournalImportRequest.HistoricalJournalLineImportRequest> lines() {
        return List.of(line("1", 1, 1L, "1", "10.00", "0.00", Map.of("office", "1")),
                line("2", 2, 2L, "2", "0.00", "10.00", Map.of("office", "2")));
    }

    private HistoricalJournalImportRequest request(List<HistoricalJournalImportRequest.HistoricalJournalLineImportRequest> values,
            LocalDate entryDate, LocalDate cutoffDate) {
        return new HistoricalJournalImportRequest("arissto-gl-v1", "ARISSTO", "001", "001", "00065", "10", "2025120010", entryDate, "001",
                "1", "3", "0", "0", "header concept", fieldHash("CNT_PARTIDAS.CONCEPTO", "header concept"), "header description",
                fieldHash("CNT_PARTIDAS.DESCRIPCION", "header description"), HASH, HASH, HASH, HASH, "fineract-gl-code-v1", HASH,
                "fineract-office-external-id-v1", HASH, "13", HASH, "legacy-text-v1", "source-fingerprint", "target-fingerprint", HASH,
                cutoffDate, "America/El_Salvador", 2L, HASH, "plan-id", "run-id", "2025120010", "USD", new BigDecimal("10.00"),
                new BigDecimal("10.00"), false, null, values);
    }

    private HistoricalJournalImportRequest.HistoricalJournalLineImportRequest line(String id, int sequence, long officeId,
            String officeExternalId, String debit, String credit, Map<String, String> dimensions) {
        String concept = "line " + id;
        String description = "display " + id;
        return new HistoricalJournalImportRequest.HistoricalJournalLineImportRequest(id, sequence, HASH, id, "1110010101", "1110010199", 7L,
                new BigDecimal(debit), new BigDecimal(credit), null, null, "00" + officeId, officeId, officeExternalId, dimensions, concept,
                fieldHash("CNT_DETALLE_PARTIDAS.CONCEPTO", concept), null, fieldHash("CNT_DETALLE_PARTIDAS.CONCEPTO_AUX", null),
                description, fieldHash("acc_gl_journal_entry.description", description), false, false, null);
    }

    private Office office(Long id, String externalId) {
        Office value = mock(Office.class);
        when(value.getId()).thenReturn(id);
        when(value.getExternalId()).thenReturn(new ExternalId(externalId));
        return value;
    }

    private HistoricalJournalLineProvenance importedLine(Long journalEntryId) {
        HistoricalJournalLineProvenance line = mock(HistoricalJournalLineProvenance.class);
        JournalEntry journalEntry = journalEntry(journalEntryId);
        when(line.getTargetJournalEntry()).thenReturn(journalEntry);
        return line;
    }

    private JournalEntry journalEntry(Long id) {
        JournalEntry entry = mock(JournalEntry.class);
        when(entry.getId()).thenReturn(id);
        return entry;
    }

    private String fieldHash(String field, String value) {
        return sha256(field + "\0" + (value == null ? "<NULL>" : value));
    }

    private String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
