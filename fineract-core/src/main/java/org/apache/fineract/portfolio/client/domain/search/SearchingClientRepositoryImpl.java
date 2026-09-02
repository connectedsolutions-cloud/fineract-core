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
package org.apache.fineract.portfolio.client.domain.search;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.TypedQuery;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.persistence.criteria.CriteriaQuery;
import jakarta.persistence.criteria.Join;
import jakarta.persistence.criteria.JoinType;
import jakarta.persistence.criteria.Order;
import jakarta.persistence.criteria.Path;
import jakarta.persistence.criteria.Predicate;
import jakarta.persistence.criteria.Root;
import jakarta.persistence.criteria.Subquery;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.jpa.CriteriaQueryFactory;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientIdentifier;
import org.apache.fineract.portfolio.client.domain.ClientTagMapping;
import org.apache.fineract.portfolio.client.domain.CredesalClientStaffAssignment;
import org.apache.fineract.portfolio.client.domain.CredesalLoanStaffAssignment;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Repository;

@Repository
@RequiredArgsConstructor
public class SearchingClientRepositoryImpl implements SearchingClientRepository {

    @PersistenceContext
    private EntityManager entityManager;

    private final CriteriaQueryFactory criteriaQueryFactory;

    @Override
    public Page<SearchedClient> searchByText(ClientSearchCriteria criteria, Pageable pageable, String officeHierarchy) {
        /*
         * this whole thing can be replaced with Spring Data JPA 3+ with a findBy(Specification, Pageable) call but at
         * this point the upgrade is too costly
         *
         * https://github.com/spring-projects/spring-data-jpa/issues/2499
         */
        ClientSearchCriteria searchCriteria = criteria == null ? new ClientSearchCriteria() : criteria;
        String hierarchyLikeValue = officeHierarchy + "%";

        CriteriaBuilder cb = entityManager.getCriteriaBuilder();
        CriteriaQuery<SearchedClient> query = cb.createQuery(SearchedClient.class);

        Root<Client> root = query.from(Client.class);
        Path<Office> office = root.get("office");

        Specification<Client> spec = (r, q, builder) -> {
            Path<Office> o = r.get("office");

            List<Predicate> predicates = new ArrayList<>();
            predicates.add(builder.like(o.get("hierarchy"), hierarchyLikeValue));

            if (StringUtils.isNotBlank(searchCriteria.getSearchText())) {
                Join<Client, ClientIdentifier> identity = r.join("identifiers", JoinType.LEFT);
                String searchLikeValue = "%" + searchCriteria.getSearchText() + "%";
                predicates.add(builder.or(builder.like(r.get("accountNumber"), searchLikeValue),
                        builder.like(r.get("displayName"), searchLikeValue), builder.like(r.get("externalId"), searchLikeValue),
                        builder.like(r.get("mobileNo"), searchLikeValue), builder.like(identity.get("documentKey"), searchLikeValue)));
            }
            if (searchCriteria.getOfficeId() != null) {
                predicates.add(builder.equal(o.get("id"), searchCriteria.getOfficeId()));
            }
            if (searchCriteria.getStatus() != null) {
                predicates.add(builder.equal(r.get("status"), searchCriteria.getStatus()));
            }
            if (searchCriteria.getTagId() != null && q != null) {
                Subquery<Long> tagSubquery = q.subquery(Long.class);
                Root<ClientTagMapping> mapping = tagSubquery.from(ClientTagMapping.class);
                tagSubquery.select(mapping.get("client").get("id"));
                tagSubquery.where(builder.equal(mapping.get("client").get("id"), r.get("id")),
                        builder.equal(mapping.get("tag").get("id"), searchCriteria.getTagId()));
                predicates.add(builder.exists(tagSubquery));
            }
            if (searchCriteria.getPromoterStaffId() != null && q != null) {
                predicates.add(existsStaffAssignment(q, builder, r, "promoterStaffId", searchCriteria.getPromoterStaffId()));
            }
            if (searchCriteria.getAccountExecutiveStaffId() != null && q != null) {
                predicates.add(existsStaffAssignment(q, builder, r, "accountExecutiveStaffId",
                        searchCriteria.getAccountExecutiveStaffId()));
            }
            if (searchCriteria.getCollectionsManagerStaffId() != null && q != null) {
                predicates.add(existsStaffAssignment(q, builder, r, "collectionsManagerStaffId",
                        searchCriteria.getCollectionsManagerStaffId()));
            }

            return builder.and(predicates.toArray(new Predicate[0]));
        };
        criteriaQueryFactory.applySpecificationToCriteria(root, spec, query);

        List<Order> orders = criteriaQueryFactory.ordersFromPageable(pageable, cb, root, () -> cb.desc(root.get("id")));
        query.orderBy(orders);

        query.select(cb.construct(SearchedClient.class, root.get("id"), root.get("displayName"), root.get("externalId"),
                root.get("accountNumber"), office.get("id"), office.get("name"), root.get("mobileNo"), root.get("status"),
                root.get("activationDate"), root.get("createdDate")));

        TypedQuery<SearchedClient> queryToExecute = entityManager.createQuery(query);

        return criteriaQueryFactory.readPage(queryToExecute, Client.class, pageable, spec);
    }

    private Predicate existsStaffAssignment(CriteriaQuery<?> query, CriteriaBuilder builder, Root<Client> clientRoot, String staffField,
            Long staffId) {
        Subquery<Long> assignmentSubquery = query.subquery(Long.class);
        Root<CredesalClientStaffAssignment> assignment = assignmentSubquery.from(CredesalClientStaffAssignment.class);
        assignmentSubquery.select(assignment.get("clientId"));
        assignmentSubquery.where(builder.equal(assignment.get("clientId"), clientRoot.get("id")),
                builder.equal(assignment.get(staffField), staffId));
        Subquery<Long> loanAssignmentSubquery = query.subquery(Long.class);
        Root<CredesalLoanStaffAssignment> loanAssignment = loanAssignmentSubquery.from(CredesalLoanStaffAssignment.class);
        loanAssignmentSubquery.select(loanAssignment.get("clientId"));
        loanAssignmentSubquery.where(builder.equal(loanAssignment.get("clientId"), clientRoot.get("id")),
                builder.equal(loanAssignment.get(staffField), staffId));
        return builder.or(builder.exists(assignmentSubquery), builder.exists(loanAssignmentSubquery));
    }
}
