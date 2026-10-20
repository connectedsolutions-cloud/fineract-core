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

    /**
     * Steps tied to a client directly, through a loan, savings (including fixed and recurring deposits), or share
     * account, or through a committee session whose selection includes one of those accounts.
     * {@code statusList} is a comma-separated status list; an empty string returns every status.
     */
    @Query(value = """
            WITH params AS (
                SELECT CAST(:clientId AS bigint) AS client_id,
                       CAST(:clientId AS text) AS client_text,
                       CAST(:statusList AS text) AS status_list
            )
            SELECT DISTINCT ps.*
            FROM m_pending_step ps
            CROSS JOIN params p
            WHERE (
                p.status_list = ''
                OR ps.status = ANY (string_to_array(p.status_list, ','))
            )
            AND (
                (ps."references"::jsonb -> 'm_client' ->> 'id') = p.client_text
                OR EXISTS (
                    SELECT 1 FROM m_loan l
                    WHERE l.client_id = p.client_id
                      AND (ps."references"::jsonb -> 'm_loan' ->> 'id') ~ '^[0-9]+$'
                      AND (ps."references"::jsonb -> 'm_loan' ->> 'id')::bigint = l.id
                )
                OR EXISTS (
                    SELECT 1 FROM m_savings_account sa
                    WHERE sa.client_id = p.client_id
                      AND (ps."references"::jsonb -> 'm_savings_account' ->> 'id') ~ '^[0-9]+$'
                      AND (ps."references"::jsonb -> 'm_savings_account' ->> 'id')::bigint = sa.id
                )
                OR EXISTS (
                    SELECT 1 FROM m_share_account sh
                    WHERE sh.client_id = p.client_id
                      AND (ps."references"::jsonb -> 'm_share_account' ->> 'id') ~ '^[0-9]+$'
                      AND (ps."references"::jsonb -> 'm_share_account' ->> 'id')::bigint = sh.id
                )
                OR EXISTS (
                    SELECT 1
                    FROM m_sesiones_comite sc
                    CROSS JOIN LATERAL jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(sc.selection) = 'array' THEN sc.selection
                            ELSE '[]'::jsonb
                        END
                    ) sel
                    WHERE (ps."references"::jsonb -> 'm_sesiones_comite' ->> 'id') = sc.id::text
                      AND (sel->>'selected_id') ~ '^[0-9]+$'
                      AND (
                          (
                              sel->>'selected_from_table_name' = 'm_loan'
                              AND EXISTS (
                                  SELECT 1 FROM m_loan l
                                  WHERE l.id = (sel->>'selected_id')::bigint
                                    AND l.client_id = p.client_id
                              )
                          )
                          OR (
                              sel->>'selected_from_table_name' = 'm_savings_account'
                              AND EXISTS (
                                  SELECT 1 FROM m_savings_account sa
                                  WHERE sa.id = (sel->>'selected_id')::bigint
                                    AND sa.client_id = p.client_id
                              )
                          )
                          OR (
                              sel->>'selected_from_table_name' = 'm_share_account'
                              AND EXISTS (
                                  SELECT 1 FROM m_share_account sh
                                  WHERE sh.id = (sel->>'selected_id')::bigint
                                    AND sh.client_id = p.client_id
                              )
                          )
                      )
                )
            )
            ORDER BY ps.creation_date DESC
            """, nativeQuery = true)
    List<PendingStep> findRelatedToClient(@Param("clientId") String clientId, @Param("statusList") String statusList);

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

    @Query("SELECT ps FROM PendingStep ps JOIN ps.pendingFlow pf WHERE pf.creator.id = :userId AND ps.responsableUser IS NOT NULL AND ps.responsableUser.id <> :userId AND ps.status IN :statuses ORDER BY ps.creationDate DESC")
    List<PendingStep> findByPendingFlowCreatorIdAndAssignedToOthersAndStatusInOrderByCreationDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses);

    @Query("SELECT ps FROM PendingStep ps JOIN ps.pendingFlow pf WHERE pf.creator.id = :userId AND ps.responsableUser IS NOT NULL AND ps.responsableUser.id <> :userId AND ps.status IN :statuses AND ps.office.id = :officeId ORDER BY ps.creationDate DESC")
    List<PendingStep> findByPendingFlowCreatorIdAndAssignedToOthersAndStatusInAndOfficeIdOrderByCreationDateDesc(
            @Param("userId") Long userId, @Param("statuses") List<String> statuses, @Param("officeId") Long officeId);

    @Query("SELECT ps FROM PendingStep ps JOIN ps.pendingFlow pf WHERE pf.creator.id = :userId AND ps.responsableUser IS NOT NULL AND ps.responsableUser.id <> :userId AND ps.status IN :statuses ORDER BY COALESCE(ps.completionDate, ps.creationDate) DESC")
    List<PendingStep> findByPendingFlowCreatorIdAndAssignedToOthersAndStatusInOrderByCompletionDateDesc(@Param("userId") Long userId,
            @Param("statuses") List<String> statuses);

    @Query("SELECT ps FROM PendingStep ps JOIN ps.pendingFlow pf WHERE pf.creator.id = :userId AND ps.responsableUser IS NOT NULL AND ps.responsableUser.id <> :userId AND ps.status IN :statuses AND ps.office.id = :officeId ORDER BY COALESCE(ps.completionDate, ps.creationDate) DESC")
    List<PendingStep> findByPendingFlowCreatorIdAndAssignedToOthersAndStatusInAndOfficeIdOrderByCompletionDateDesc(
            @Param("userId") Long userId, @Param("statuses") List<String> statuses, @Param("officeId") Long officeId);
}
