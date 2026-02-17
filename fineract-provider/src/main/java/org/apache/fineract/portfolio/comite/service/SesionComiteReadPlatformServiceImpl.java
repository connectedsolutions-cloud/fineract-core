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
package org.apache.fineract.portfolio.comite.service;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.service.SearchParameters;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.comite.data.ApprovedLoansDisbursementSumData;
import org.apache.fineract.portfolio.comite.data.LoanSelectionData;
import org.apache.fineract.portfolio.comite.data.SesionComiteData;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.comite.domain.SesionComiteRepository;
import org.apache.fineract.portfolio.comite.exception.SesionComiteNotFoundException;
import org.apache.fineract.portfolio.loanaccount.data.LoanAccountData;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepository;
import org.apache.fineract.portfolio.loanaccount.service.LoanReadPlatformService;
import org.springframework.stereotype.Service;

@RequiredArgsConstructor
@Service
public class SesionComiteReadPlatformServiceImpl implements SesionComiteReadPlatformService {

    private final SesionComiteRepository sesionComiteRepository;
    private final PlatformSecurityContext context;
    private final LoanReadPlatformService loanReadPlatformService;
    private final LoanRepository loanRepository;
    private final FromJsonHelper fromJsonHelper;

    @Override
    public List<SesionComiteData> retrieveAllSessions() {
        final Long officeId = this.context.authenticatedUser().getOffice().getId();
        final List<SesionComite> sessions = this.sesionComiteRepository.findByOfficeIdOrderByCreatedAtDesc(officeId);
        return sessions.stream().map(this::mapToData).collect(Collectors.toList());
    }

    @Override
    public SesionComiteData retrieveOneSession(Long sessionId) {
        final Long officeId = this.context.authenticatedUser().getOffice().getId();
        final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));
        return mapToData(session);
    }

    @Override
    public List<LoanAccountData> retrievePendingLoansForUser(Long currentOfficeId) {
        // Get loans with status 'pending approval' (status=100)
        // Filter by user's office hierarchy/permissions or specific office if currentOfficeId is provided
        // Similar to getAllLoansToBeApproved in TasksService
        // If currentOfficeId is null, use the logged-in user's office ID
        final Long officeIdToUse = currentOfficeId != null ? currentOfficeId
                : this.context.authenticatedUser().getOffice().getId();
        
        final SearchParameters searchParameters = SearchParameters.builder()
                .status("100") // SUBMITTED_AND_PENDING_APPROVAL
                .limit(1000) // Similar to TasksService.getAllLoansToBeApproved
                .currentOfficeId(officeIdToUse) // Filter by specific office
                .build();
        
        // retrieveAll will filter by the specified office when currentOfficeId is set
        final var loanPage = this.loanReadPlatformService.retrieveAll(searchParameters);
        final List<LoanAccountData> allPending = loanPage.getPageItems();
        // Only include loans that are ready for committee (ready_for_comite = true)
        return allPending.stream()
                .filter(loan -> Boolean.TRUE.equals(loan.getReadyForComite()))
                .collect(Collectors.toList());
    }

    @Override
    public List<Long> retrieveApprovedLoanIds(Long sessionId, Long officeId) {
        return this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                .map(this::mapToData)
                .map(data -> {
                    List<Long> ids = data.getUnanimouslyApprovedLoanIds();
                    return ids != null ? ids : new ArrayList<Long>();
                })
                .orElse(new ArrayList<>());
    }

    @Override
    public ApprovedLoansDisbursementSumData retrieveApprovedLoansDisbursementSum(Long sessionId, Long officeId) {
        if (sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId).isEmpty()) {
            return null;
        }
        List<Long> loanIds = retrieveApprovedLoanIds(sessionId, officeId);
        if (loanIds.isEmpty()) {
            return new ApprovedLoansDisbursementSumData(BigDecimal.ZERO, null, null);
        }
        BigDecimal sum = loanRepository.sumNetDisbursalAmountByIdIn(loanIds);
        if (sum == null) {
            sum = BigDecimal.ZERO;
        }
        String currencyCode = null;
        Integer currencyDigits = null;
        var firstLoan = loanRepository.findById(loanIds.get(0));
        if (firstLoan.isPresent()) {
            Loan loan = firstLoan.get();
            currencyCode = loan.getCurrencyCode();
            if (loan.getCurrency() != null) {
                currencyDigits = loan.getCurrency().getDigitsAfterDecimal();
            }
        }
        return new ApprovedLoansDisbursementSumData(sum, currencyCode, currencyDigits);
    }

    private SesionComiteData mapToData(SesionComite session) {
        SesionComiteData data = new SesionComiteData();
        data.setId(session.getId());
        data.setOfficeId(session.getOffice().getId());
        data.setOfficeName(session.getOffice().getName());
        data.setIntegrantes(parseJsonArray(session.getIntegrantes()));
        data.setCreatorId(session.getCreator().getId());
        data.setCreatorName(session.getCreator().getDisplayName());
        data.setCreatedAt(session.getCreatedAt());
        data.setSelection(parseSelectionJson(session.getSelection()));
        data.setDescription(session.getDescription());
        data.setSesionStartDate(session.getSesionStartDate());
        data.setStatus(session.getStatus());
        data.setClosingDate(session.getClosingDate());
        data.setOutput(parseJsonStringArray(session.getOutput()));
        data.setType(session.getType());
        data.setName(session.getName());

        // Calculate counts
        List<Long> integrantesList = parseJsonArray(session.getIntegrantes());
        data.setParticipantCount(integrantesList != null ? integrantesList.size() : 0);
        // Calculate submitted count based on selections
        data.setSubmittedCount(0); // TODO: Implement submission tracking

        // Compute unanimously approved loan IDs (backend-only; frontend consumes via GET)
        List<LoanSelectionData> selectionList = data.getSelection();
        data.setUnanimouslyApprovedLoanIds(
                computeUnanimouslyApprovedLoanIds(integrantesList, selectionList));

        return data;
    }

    private List<Long> computeUnanimouslyApprovedLoanIds(List<Long> integrantes,
            List<LoanSelectionData> selection) {
        if (integrantes == null || integrantes.isEmpty() || selection == null || selection.isEmpty()) {
            return new ArrayList<>();
        }
        Map<Long, Set<Long>> loanToParticipants = new HashMap<>();
        for (LoanSelectionData s : selection) {
            if (s.getSelectedId() != null && s.getAppuserId() != null) {
                loanToParticipants
                        .computeIfAbsent(s.getSelectedId(), k -> new HashSet<>())
                        .add(s.getAppuserId());
            }
        }
        Set<Long> integrantesSet = new HashSet<>(integrantes);
        List<Long> unanimouslyApproved = new ArrayList<>();
        for (Map.Entry<Long, Set<Long>> e : loanToParticipants.entrySet()) {
            if (e.getValue().equals(integrantesSet)) {
                unanimouslyApproved.add(e.getKey());
            }
        }
        return unanimouslyApproved;
    }

    private List<Long> parseJsonArray(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            JsonArray array = fromJsonHelper.parse(json).getAsJsonArray();
            List<Long> result = new ArrayList<>();
            for (JsonElement element : array) {
                result.add(element.getAsLong());
            }
            return result;
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private List<String> parseJsonStringArray(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            JsonArray array = fromJsonHelper.parse(json).getAsJsonArray();
            List<String> result = new ArrayList<>();
            for (JsonElement element : array) {
                result.add(element.getAsString());
            }
            return result;
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private List<LoanSelectionData> parseSelectionJson(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            JsonArray array = fromJsonHelper.parse(json).getAsJsonArray();
            List<LoanSelectionData> result = new ArrayList<>();
            for (JsonElement element : array) {
                var obj = element.getAsJsonObject();
                LoanSelectionData selection = new LoanSelectionData();
                if (obj.has("appuser_id")) {
                    selection.setAppuserId(obj.get("appuser_id").getAsLong());
                }
                if (obj.has("selected_id")) {
                    selection.setSelectedId(obj.get("selected_id").getAsLong());
                }
                if (obj.has("selected_from_table_name")) {
                    selection.setSelectedFromTableName(obj.get("selected_from_table_name").getAsString());
                }
                if (obj.has("selected_date")) {
                    selection.setSelectedDate(OffsetDateTime.parse(obj.get("selected_date").getAsString()));
                }
                if (obj.has("user_note")) {
                    selection.setUserNote(obj.get("user_note").getAsString());
                }
                result.add(selection);
            }
            return result;
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }
}
