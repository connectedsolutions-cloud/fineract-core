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
import com.google.gson.JsonObject;
import jakarta.persistence.PersistenceException;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.apache.commons.lang3.exception.ExceptionUtils;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.ErrorHandler;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.comite.domain.SesionComite;
import org.apache.fineract.portfolio.comite.domain.SesionComiteRepository;
import org.apache.fineract.portfolio.comite.exception.SesionComiteNotFoundException;
import org.apache.fineract.portfolio.loanaccount.service.LoanApplicationWritePlatformService;
import org.springframework.stereotype.Service;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.orm.jpa.JpaSystemException;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@RequiredArgsConstructor
@Service
public class SesionComiteWritePlatformServiceImpl implements SesionComiteWritePlatformService {

    private final SesionComiteRepository sesionComiteRepository;
    private final PlatformSecurityContext context;
    private final LoanApplicationWritePlatformService loanApplicationWritePlatformService;
    private final FromJsonHelper fromJsonHelper;

    @Transactional
    @Override
    public CommandProcessingResult createSession(JsonCommand command) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();

            // Parse integrantes
            JsonArray integrantesArray = command.arrayOfParameterNamed("integrantes");
            List<Long> integrantes = new ArrayList<>();
            if (integrantesArray != null) {
                for (JsonElement element : integrantesArray) {
                    integrantes.add(element.getAsLong());
                }
            }

            // Generate name if not provided
            String name = command.stringValueOfParameterNamed("name");
            if (StringUtils.isBlank(name)) {
                DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
                name = "comite otorgamiento - " + OffsetDateTime.now().format(formatter);
            }

            // Create session
            SesionComite session = new SesionComite();
            session.setOffice(currentUser.getOffice());
            session.setIntegrantes(jsonArrayToString(integrantesArray));
            session.setCreator(currentUser);
            session.setCreatedAt(DateUtils.getAuditOffsetDateTime());
            session.setSelection(null);
            session.setDescription(command.stringValueOfParameterNamed("description"));
            session.setSesionStartDate(null);
            session.setStatus("created");
            session.setClosingDate(null);
            session.setOutput(null);
            session.setType(command.stringValueOfParameterNamed("type"));
            if (StringUtils.isBlank(session.getType())) {
                session.setType("comite_otorgamiento");
            }
            session.setName(name);

            logSesionComitePayload("createSession", session);
            this.sesionComiteRepository.saveAndFlush(session);

            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(session.getId()).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(command, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(command, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult updateSession(Long sessionId, JsonCommand command) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            // Verify session not started
            if ("started".equals(session.getStatus()) || "applied".equals(session.getStatus()) || "closed".equals(session.getStatus())) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.cannot.update",
                        "Cannot update session in status: " + session.getStatus());
            }

            Map<String, Object> changes = new HashMap<>();

            // Update integrantes
            if (command.hasParameter("integrantes")) {
                JsonArray integrantesArray = command.arrayOfParameterNamed("integrantes");
                session.setIntegrantes(jsonArrayToString(integrantesArray));
                changes.put("integrantes", integrantesArray);
            }

            // Update name
            if (command.hasParameter("name")) {
                String name = command.stringValueOfParameterNamed("name");
                session.setName(name);
                changes.put("name", name);
            }

            // Update description
            if (command.hasParameter("description")) {
                String description = command.stringValueOfParameterNamed("description");
                session.setDescription(description);
                changes.put("description", description);
            }

            // Update type
            if (command.hasParameter("type")) {
                String type = command.stringValueOfParameterNamed("type");
                session.setType(type);
                changes.put("type", type);
            }

            if (!changes.isEmpty()) {
                logSesionComitePayload("updateSession", session);
                this.sesionComiteRepository.saveAndFlush(session);
            }

            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(sessionId).with(changes)
                    .build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(command, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(command, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult startSession(Long sessionId) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            if (!"created".equals(session.getStatus())) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.cannot.start",
                        "Session must be in 'created' status to start");
            }

            session.setStatus("started");
            session.setSesionStartDate(DateUtils.getAuditOffsetDateTime());

            logSesionComitePayload("startSession", session);
            this.sesionComiteRepository.saveAndFlush(session);

            return new CommandProcessingResultBuilder().withEntityId(sessionId).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(null, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(null, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult updateParticipantSelections(Long sessionId, JsonCommand command) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();
            final Long currentUserId = currentUser.getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            if (!"started".equals(session.getStatus())) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.not.started",
                        "Session must be in 'started' status to update selections");
            }

            // Verify user is a participant
            List<Long> integrantes = parseJsonArray(session.getIntegrantes());
            if (!integrantes.contains(currentUserId)) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.not.participant",
                        "User is not a participant in this session");
            }

            // Parse current selections
            JsonArray selectionsArray = command.arrayOfParameterNamed("selection");
            List<JsonObject> currentUserSelections = new ArrayList<>();

            if (selectionsArray != null) {
                for (JsonElement element : selectionsArray) {
                    JsonObject selection = element.getAsJsonObject();
                    selection.addProperty("appuser_id", currentUserId);
                    if (!selection.has("selected_date")) {
                        selection.addProperty("selected_date", OffsetDateTime.now().toString());
                    }
                    currentUserSelections.add(selection);
                }
            }

            // Parse existing selections and update
            List<JsonObject> allSelections = parseSelectionJsonArray(session.getSelection());
            
            // Remove existing selections from this user
            allSelections.removeIf(sel -> sel.has("appuser_id") && sel.get("appuser_id").getAsLong() == currentUserId);
            
            // Add new selections from this user
            allSelections.addAll(currentUserSelections);

            // Convert back to JSON string
            JsonArray updatedSelectionsArray = new JsonArray();
            for (JsonObject sel : allSelections) {
                updatedSelectionsArray.add(sel);
            }
            session.setSelection(updatedSelectionsArray.toString());

            logSesionComitePayload("updateParticipantSelections", session);
            this.sesionComiteRepository.saveAndFlush(session);

            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(sessionId).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(command, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(command, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult submitSession(Long sessionId) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            if (!"started".equals(session.getStatus())) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.not.started",
                        "Session must be in 'started' status to submit");
            }

            // Mark participant as submitted (could add a separate submitted_users field or track in selection)
            // For now, submission is implicit - all participants need to have selections
            // TODO: Add explicit submission tracking if needed

            return new CommandProcessingResultBuilder().withEntityId(sessionId).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(null, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(null, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult applySessionApprovals(Long sessionId) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            if (!"started".equals(session.getStatus())) {
                throw new PlatformDataIntegrityException("error.msg.sesion.comite.not.started",
                        "Session must be in 'started' status to apply approvals");
            }

            // Get unanimously approved loans
            List<Long> unanimouslyApprovedLoanIds = getUnanimouslyApprovedLoans(session);

            // Batch approve loans
            List<String> transactionIds = new ArrayList<>();
            for (Long loanId : unanimouslyApprovedLoanIds) {
                try {
                    // Create approval command for this loan
                    String jsonCommand = String.format("{\"dateFormat\":\"yyyy-MM-dd\",\"locale\":\"en\",\"approvedOnDate\":\"%s\"}",
                            OffsetDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE));
                    com.google.gson.JsonElement parsedCommand = fromJsonHelper.parse(jsonCommand);
                    JsonCommand approvalCommand = JsonCommand.from(jsonCommand, parsedCommand, fromJsonHelper, "LOAN", loanId, null,
                            null, null, loanId, null, null, null, null, null, null, null, null);

                    CommandProcessingResult result = loanApplicationWritePlatformService.approveApplication(loanId, approvalCommand);
                    if (result.getLoanId() != null) {
                        transactionIds.add(result.getLoanId().toString());
                    }
                } catch (Exception e) {
                    log.error("Error approving loan " + loanId, e);
                }
            }

            // Update session
            session.setStatus("applied");
            JsonArray outputArray = new JsonArray();
            for (String txId : transactionIds) {
                outputArray.add(txId);
            }
            session.setOutput(outputArray.toString());
            session.setClosingDate(DateUtils.getAuditOffsetDateTime());

            logSesionComitePayload("applySessionApprovals", session);
            this.sesionComiteRepository.saveAndFlush(session);

            return new CommandProcessingResultBuilder().withEntityId(sessionId).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(null, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(null, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult closeSession(Long sessionId) {
        try {
            final AppUser currentUser = this.context.authenticatedUser();
            final Long officeId = currentUser.getOffice().getId();

            final SesionComite session = this.sesionComiteRepository.findByIdAndOfficeId(sessionId, officeId)
                    .orElseThrow(() -> new SesionComiteNotFoundException(sessionId));

            session.setStatus("closed");
            session.setClosingDate(DateUtils.getAuditOffsetDateTime());

            logSesionComitePayload("closeSession", session);
            this.sesionComiteRepository.saveAndFlush(session);

            return new CommandProcessingResultBuilder().withEntityId(sessionId).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleDataIntegrityIssues(null, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleDataIntegrityIssues(null, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    private List<Long> getUnanimouslyApprovedLoans(SesionComite session) {
        List<Long> integrantes = parseJsonArray(session.getIntegrantes());
        List<JsonObject> selections = parseSelectionJsonArray(session.getSelection());

        // Group selections by loan ID
        Map<Long, Set<Long>> loanToParticipants = new HashMap<>();
        for (JsonObject selection : selections) {
            if (selection.has("selected_id")) {
                Long loanId = selection.get("selected_id").getAsLong();
                Long participantId = selection.get("appuser_id").getAsLong();
                loanToParticipants.computeIfAbsent(loanId, k -> new HashSet<>()).add(participantId);
            }
        }

        // Find loans where all participants have selected
        List<Long> unanimouslyApproved = new ArrayList<>();
        Set<Long> integrantesSet = new HashSet<>(integrantes);
        for (Map.Entry<Long, Set<Long>> entry : loanToParticipants.entrySet()) {
            if (entry.getValue().equals(integrantesSet)) {
                unanimouslyApproved.add(entry.getKey());
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

    private List<JsonObject> parseSelectionJsonArray(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            JsonArray array = fromJsonHelper.parse(json).getAsJsonArray();
            List<JsonObject> result = new ArrayList<>();
            for (JsonElement element : array) {
                result.add(element.getAsJsonObject());
            }
            return result;
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private String jsonArrayToString(JsonArray array) {
        return array != null ? array.toString() : null;
    }

    /**
     * Debug logging: outputs exactly what is being sent to the DB for JSONB columns (integrantes, selection, output).
     * Enable DEBUG for {@code org.apache.fineract.portfolio.comite} to see these logs.
     */
    private void logSesionComitePayload(String operation, SesionComite session) {
        if (log.isDebugEnabled()) {
            log.debug("[SesionComite DB persist] operation={} id={} officeId={} status={}",
                    operation, session.getId(), session.getOffice() != null ? session.getOffice().getId() : null,
                    session.getStatus());
            log.debug("[SesionComite DB persist] integrantes (exact value sent to DB): {}", session.getIntegrantes());
            log.debug("[SesionComite DB persist] selection (exact value sent to DB): {}", session.getSelection());
            log.debug("[SesionComite DB persist] output (exact value sent to DB): {}", session.getOutput());
        }
    }

    private void handleDataIntegrityIssues(JsonCommand command, Throwable realCause, Exception dve) {
        log.error("Error occurred.", dve);
        throw ErrorHandler.getMappable(dve, "error.msg.sesion.comite.unknown.data.integrity.issue",
                "Unknown data integrity issue with resource: " + realCause.getMessage());
    }
}
