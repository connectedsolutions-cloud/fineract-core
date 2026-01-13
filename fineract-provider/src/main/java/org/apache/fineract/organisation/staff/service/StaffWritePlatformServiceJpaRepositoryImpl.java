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
package org.apache.fineract.organisation.staff.service;

import jakarta.persistence.PersistenceException;
import java.util.HashSet;
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
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepositoryWrapper;
import org.apache.fineract.organisation.staff.domain.Staff;
import org.apache.fineract.organisation.staff.domain.StaffRepository;
import org.apache.fineract.organisation.staff.exception.StaffNotFoundException;
import org.apache.fineract.organisation.staff.serialization.StaffCommandFromApiJsonDeserializer;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.orm.jpa.JpaSystemException;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@RequiredArgsConstructor
public class StaffWritePlatformServiceJpaRepositoryImpl implements StaffWritePlatformService {

    private final StaffCommandFromApiJsonDeserializer fromApiJsonDeserializer;
    private final StaffRepository staffRepository;
    private final OfficeRepositoryWrapper officeRepositoryWrapper;

    @Transactional
    @Override
    public CommandProcessingResult createStaff(final JsonCommand command) {

        try {
            this.fromApiJsonDeserializer.validateForCreate(command.json());

            Office primaryOffice = null;
            Set<Office> offices = new HashSet<>();
            Long primaryOfficeId = null;

            // Handle officeIds array (multiple offices) or single officeId for backward compatibility
            if (command.hasParameter("officeIds")) {
                final String[] officeIdsStr = command.arrayValueOfParameterNamed("officeIds");
                if (officeIdsStr != null && officeIdsStr.length > 0) {
                    // Parse all office IDs and fetch offices
                    for (String officeIdStr : officeIdsStr) {
                        final Long officeId = Long.parseLong(officeIdStr);
                        final Office office = this.officeRepositoryWrapper.findOneWithNotFoundDetection(officeId);
                        offices.add(office);
                    }
                    // First office becomes primary office (if offices exist)
                    if (!offices.isEmpty()) {
                        primaryOffice = offices.iterator().next();
                        primaryOfficeId = primaryOffice.getId();
                    }
                }
            } else if (command.hasParameter("officeId")) {
                // Backward compatibility: single officeId
                primaryOfficeId = command.longValueOfParameterNamed("officeId");
                primaryOffice = this.officeRepositoryWrapper.findOneWithNotFoundDetection(primaryOfficeId);
                offices.add(primaryOffice);
            }

            // Validate that at least one office is provided
            if (offices.isEmpty() && primaryOffice == null) {
                throw new PlatformDataIntegrityException("error.msg.staff.office.required",
                        "At least one office must be assigned to the staff");
            }

            // Create staff - always use a primary office for now (even though migration makes it nullable)
            // This ensures backward compatibility and avoids constraint issues until migration runs
            final Staff staff;
            if (!offices.isEmpty()) {
                // Use first office as primary for creation (will be stored in office_id column)
                if (primaryOffice == null) {
                    primaryOffice = offices.iterator().next();
                    primaryOfficeId = primaryOffice.getId();
                }
                staff = Staff.fromJson(primaryOffice, command);
                // Set all offices after creation - this will ensure primary office is in the set
                staff.setOffices(offices);
            } else if (primaryOffice != null) {
                // Backward compatibility: single officeId provided
                staff = Staff.fromJson(primaryOffice, command);
                if (!offices.isEmpty()) {
                    staff.setOffices(offices);
                }
            } else {
                // This shouldn't happen due to validation above, but handle it
                throw new PlatformDataIntegrityException("error.msg.staff.office.required",
                        "At least one office must be assigned to the staff");
            }

            // Final check: ensure office is set before saving (required until migration makes it nullable)
            // This should not happen if fromJson was called with a non-null primaryOffice, but handle edge cases
            if (staff.getOffice() == null) {
                if (primaryOffice != null) {
                    staff.setOffice(primaryOffice);
                    primaryOfficeId = primaryOffice.getId();
                } else {
                    // If primaryOffice is null, offices should not be empty (validated above)
                    // Access offices directly since we know it's not empty due to validation
                    final Office firstOffice = offices.iterator().next();
                    staff.setOffice(firstOffice);
                    primaryOfficeId = firstOffice.getId();
                }
            }
            
            // Ensure primaryOfficeId is set from the office for return value
            if (primaryOfficeId == null && staff.getOffice() != null) {
                primaryOfficeId = staff.getOffice().getId();
            }

            this.staffRepository.saveAndFlush(staff);

            return new CommandProcessingResultBuilder() //
                    .withCommandId(command.commandId()) //
                    .withEntityId(staff.getId()).withOfficeId(primaryOfficeId) //
                    .build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleStaffDataIntegrityIssues(command, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleStaffDataIntegrityIssues(command, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    @Transactional
    @Override
    public CommandProcessingResult updateStaff(final Long staffId, final JsonCommand command) {

        try {
            this.fromApiJsonDeserializer.validateForUpdate(command.json(), staffId);

            final Staff staffForUpdate = this.staffRepository.findById(staffId).orElseThrow(() -> new StaffNotFoundException(staffId));
            final Map<String, Object> changesOnly = staffForUpdate.update(command);

            // Handle officeIds array (multiple offices)
            if (changesOnly.containsKey("officeIds")) {
                final String[] officeIdsStr = (String[]) changesOnly.get("officeIds");
                if (officeIdsStr != null && officeIdsStr.length > 0) {
                    final Set<Office> newOffices = new HashSet<>();
                    // Parse all office IDs and fetch offices
                    for (String officeIdStr : officeIdsStr) {
                        final Long officeId = Long.parseLong(officeIdStr);
                        final Office office = this.officeRepositoryWrapper.findOneWithNotFoundDetection(officeId);
                        newOffices.add(office);
                    }
                    // First office becomes primary office
                    final Office newPrimaryOffice = newOffices.iterator().next();
                    staffForUpdate.changeOffice(newPrimaryOffice);
                    staffForUpdate.setOffices(newOffices);
                }
            } else if (changesOnly.containsKey("officeId")) {
                // Backward compatibility: handle single officeId
                final Long officeId = (Long) changesOnly.get("officeId");
                final Office newOffice = this.officeRepositoryWrapper.findOneWithNotFoundDetection(officeId);
                staffForUpdate.changeOffice(newOffice);
                // Ensure primary office is in offices set
                if (!staffForUpdate.getOffices().contains(newOffice)) {
                    staffForUpdate.addOffice(newOffice);
                }
            }

            if (!changesOnly.isEmpty()) {
                this.staffRepository.saveAndFlush(staffForUpdate);
            }

            final Long finalOfficeId = staffForUpdate.getOffice() != null ? staffForUpdate.getOffice().getId() : null;
            return new CommandProcessingResultBuilder().withCommandId(command.commandId()).withEntityId(staffId)
                    .withOfficeId(finalOfficeId).with(changesOnly).build();
        } catch (final JpaSystemException | DataIntegrityViolationException dve) {
            handleStaffDataIntegrityIssues(command, dve.getMostSpecificCause(), dve);
            return CommandProcessingResult.empty();
        } catch (final PersistenceException dve) {
            Throwable throwable = ExceptionUtils.getRootCause(dve.getCause());
            handleStaffDataIntegrityIssues(command, throwable, dve);
            return CommandProcessingResult.empty();
        }
    }

    /*
     * Guaranteed to throw an exception no matter what the data integrity issue is.
     */
    private void handleStaffDataIntegrityIssues(final JsonCommand command, final Throwable realCause, final Exception dve) {
        if (realCause.getMessage().contains("external_id")) {
            final String externalId = command.stringValueOfParameterNamed("externalId");
            throw new PlatformDataIntegrityException("error.msg.staff.duplicate.externalId",
                    "Staff with externalId `" + externalId + "` already exists", "externalId", externalId);
        } else if (realCause.getMessage().contains("display_name")) {
            final String lastname = command.stringValueOfParameterNamed("lastname");
            String displayName = lastname;
            if (!StringUtils.isBlank(displayName)) {
                final String firstname = command.stringValueOfParameterNamed("firstname");
                displayName = lastname + ", " + firstname;
            }
            throw new PlatformDataIntegrityException("error.msg.staff.duplicate.displayName",
                    "A staff with the given display name '" + displayName + "' already exists", "displayName", displayName);
        }

        log.error("Error occured.", dve);
        throw ErrorHandler.getMappable(dve, "error.msg.staff.unknown.data.integrity.issue",
                "Unknown data integrity issue with resource: " + realCause.getMessage());
    }
}
