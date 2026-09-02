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
package org.apache.fineract.portfolio.mobilecollection.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface MobileCollectionRouteRepository extends JpaRepository<MobileCollectionRoute, Long> {

    @Query("select distinct r from MobileCollectionRoute r left join fetch r.assignments a left join fetch a.client "
            + "left join fetch r.responsibleStaff left join fetch r.office order by r.routeName asc, r.id asc")
    List<MobileCollectionRoute> findAllFetched();

    @Query("select distinct r from MobileCollectionRoute r left join fetch r.assignments a left join fetch a.client "
            + "left join fetch r.responsibleStaff left join fetch r.office where r.id = :id")
    Optional<MobileCollectionRoute> findByIdFetched(@Param("id") Long id);
}
