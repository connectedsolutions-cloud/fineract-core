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
package org.apache.fineract.portfolio.client.service.search;

import java.util.List;
import java.util.Objects;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.service.PagedRequest;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.service.OfficeReadPlatformService;
import org.apache.fineract.organisation.staff.data.StaffData;
import org.apache.fineract.portfolio.client.domain.ClientRepository;
import org.apache.fineract.portfolio.client.domain.ClientStatus;
import org.apache.fineract.portfolio.client.domain.search.ClientSearchCriteria;
import org.apache.fineract.portfolio.client.service.ClientTagReadPlatformService;
import org.apache.fineract.portfolio.client.service.search.domain.ClientSearchData;
import org.apache.fineract.portfolio.client.service.search.domain.ClientSearchOptionsData;
import org.apache.fineract.portfolio.client.service.search.domain.ClientTextSearch;
import org.apache.fineract.portfolio.client.service.search.mapper.ClientSearchDataMapper;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@Transactional(readOnly = true)
@RequiredArgsConstructor
public class ClientSearchService {

    private static final String TIPO_CLIENTE_TAG_GROUP = "tipo_cliente";

    private final PlatformSecurityContext context;
    private final ClientRepository clientRepository;
    private final ClientSearchDataMapper clientSearchDataMapper;
    private final OfficeReadPlatformService officeReadPlatformService;
    private final ClientTagReadPlatformService clientTagReadPlatformService;
    private final JdbcTemplate jdbcTemplate;

    public Page<ClientSearchData> searchByText(PagedRequest<ClientTextSearch> searchRequest) {
        validateTextSearchRequest(searchRequest);
        return executeTextSearch(searchRequest);
    }

    public ClientSearchOptionsData retrieveSearchOptions(final Long officeId) {
        context.isAuthenticated();
        final String hierarchyLike = context.authenticatedUser().getOffice().getHierarchy() + "%";

        ClientSearchOptionsData options = new ClientSearchOptionsData();
        options.setOffices(officeReadPlatformService.retrieveAllOfficesForDropdown());
        options.setTags(clientTagReadPlatformService.retrieveTagsByGroup(TIPO_CLIENTE_TAG_GROUP));
        options.setPromoters(retrieveAssignedStaff(hierarchyLike, "promoter_staff_id", officeId));
        options.setAccountExecutives(retrieveAssignedStaff(hierarchyLike, "account_executive_staff_id", officeId));
        options.setCollectionsManagers(retrieveAssignedStaff(hierarchyLike, "collections_manager_staff_id", officeId));
        return options;
    }

    private void validateTextSearchRequest(PagedRequest<ClientTextSearch> searchRequest) {
        Objects.requireNonNull(searchRequest, "searchRequest must not be null");

        context.isAuthenticated();
    }

    private Page<ClientSearchData> executeTextSearch(PagedRequest<ClientTextSearch> searchRequest) {
        final String hierarchy = context.authenticatedUser().getOffice().getHierarchy();

        Optional<ClientTextSearch> request = searchRequest.getRequest();
        ClientSearchCriteria criteria = toCriteria(request.orElse(null));
        Pageable pageable = searchRequest.toPageable();

        return clientRepository.searchByText(criteria, pageable, hierarchy).map(clientSearchDataMapper::map);
    }

    private ClientSearchCriteria toCriteria(ClientTextSearch request) {
        ClientSearchCriteria criteria = new ClientSearchCriteria();
        if (request == null) {
            return criteria;
        }
        criteria.setSearchText(StringUtils.trimToNull(request.getText()));
        criteria.setOfficeId(request.getOfficeId());
        criteria.setTagId(request.getTagId());
        criteria.setPromoterStaffId(request.getPromoterStaffId());
        criteria.setAccountExecutiveStaffId(request.getAccountExecutiveStaffId());
        criteria.setCollectionsManagerStaffId(request.getCollectionsManagerStaffId());
        if (StringUtils.isNotBlank(request.getStatus())) {
            ClientStatus status = ClientStatus.fromString(request.getStatus());
            if (status.getValue() > 0) {
                criteria.setStatus(status.getValue());
            }
        }
        return criteria;
    }

    private List<StaffData> retrieveAssignedStaff(final String hierarchyLike, final String staffColumn, final Long officeId) {
        final String column = switch (staffColumn) {
            case "promoter_staff_id", "account_executive_staff_id", "collections_manager_staff_id" -> staffColumn;
            default -> throw new IllegalArgumentException("Unsupported staff assignment column");
        };
        final StringBuilder sql = new StringBuilder();
        sql.append("select distinct q.id, q.displayName from (");
        sql.append("select s.id, s.display_name as displayName, s.office_id from credesal_client_staff_assignment a ");
        sql.append("join m_staff s on s.id = a.").append(column);
        sql.append(" join m_client c on c.id = a.client_id join m_office o on o.id = c.office_id ");
        sql.append("where a.").append(column).append(" is not null and o.hierarchy like ? union ");
        sql.append("select s.id, s.display_name as displayName, s.office_id from credesal_loan_staff_assignment a ");
        sql.append("join m_staff s on s.id = a.").append(column);
        sql.append(" join m_client c on c.id = a.client_id join m_office o on o.id = c.office_id ");
        sql.append("where a.").append(column).append(" is not null and o.hierarchy like ?) q where 1=1 ");
        if (officeId != null) {
            sql.append("and (q.office_id = ? or exists (select 1 from m_staff_office so where so.staff_id = q.id and so.office_id = ?)) ");
        }
        sql.append("order by q.displayName");
        if (officeId != null) {
            return jdbcTemplate.query(sql.toString(), (rs, rowNum) -> StaffData.lookup(rs.getLong("id"), rs.getString("displayName")),
                    hierarchyLike, hierarchyLike, officeId, officeId);
        }
        return jdbcTemplate.query(sql.toString(), (rs, rowNum) -> StaffData.lookup(rs.getLong("id"), rs.getString("displayName")),
                hierarchyLike, hierarchyLike);
    }
}
