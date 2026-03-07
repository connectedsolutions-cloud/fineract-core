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
package org.apache.fineract.portfolio.pendiente.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface PendingStepRepository extends JpaRepository<PendingStep, Long>, JpaSpecificationExecutor<PendingStep> {

    List<PendingStep> findByPendingFlowIdOrderById(Long pendingFlowId);

    List<PendingStep> findByPendingFlow_IdAndOffice_IdOrderById(Long pendingFlowId, Long officeId);

    @Query("SELECT ps FROM PendingStep ps WHERE ps.responsableUser.id = :userId AND ps.status IN :statuses ORDER BY ps.creationDate DESC")
    List<PendingStep> findByResponsableUserIdAndStatusInOrderByCreationDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses);

    @Query("SELECT ps FROM PendingStep ps WHERE ps.responsableUser.id = :userId AND ps.status IN :statuses AND ps.office.id = :officeId ORDER BY ps.creationDate DESC")
    List<PendingStep> findByResponsableUserIdAndStatusInAndOfficeIdOrderByCreationDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses, @Param("officeId") Long officeId);

    List<PendingStep> findByOffice_IdOrderByCreationDateDesc(Long officeId);

    @Query("SELECT ps FROM PendingStep ps WHERE ps.responsableUser.id = :userId AND ps.status IN :statuses ORDER BY COALESCE(ps.completionDate, ps.creationDate) DESC")
    List<PendingStep> findByResponsableUserIdAndStatusInOrderByCompletionDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses);

    @Query("SELECT ps FROM PendingStep ps WHERE ps.responsableUser.id = :userId AND ps.status IN :statuses AND ps.office.id = :officeId ORDER BY COALESCE(ps.completionDate, ps.creationDate) DESC")
    List<PendingStep> findByResponsableUserIdAndStatusInAndOfficeIdOrderByCompletionDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses, @Param("officeId") Long officeId);
}
