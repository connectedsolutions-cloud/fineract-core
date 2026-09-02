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
package org.apache.fineract.integrationtests.client;

import io.restassured.builder.RequestSpecBuilder;
import io.restassured.builder.ResponseSpecBuilder;
import io.restassured.http.ContentType;
import io.restassured.path.json.JsonPath;
import io.restassured.specification.RequestSpecification;
import io.restassured.specification.ResponseSpecification;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.client.models.GetClientsClientIdResponse;
import org.apache.fineract.client.models.GetClientsResponse;
import org.apache.fineract.client.models.PageClientSearchData;
import org.apache.fineract.client.models.PostClientsClientIdIdentifiersRequest;
import org.apache.fineract.client.models.PostClientsClientIdIdentifiersResponse;
import org.apache.fineract.client.models.PostClientsRequest;
import org.apache.fineract.client.models.PostClientsResponse;
import org.apache.fineract.client.models.PostOfficesRequest;
import org.apache.fineract.client.models.PostOfficesResponse;
import org.apache.fineract.client.models.SortOrder;
import org.apache.fineract.integrationtests.common.ClientHelper;
import org.apache.fineract.integrationtests.common.Utils;
import org.apache.fineract.integrationtests.common.organisation.StaffHelper;
import org.apache.fineract.integrationtests.common.system.DatatableHelper;
import org.assertj.core.api.Assertions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

public class ClientSearchTest extends IntegrationTest {

    private ResponseSpecification responseSpec;
    private RequestSpecification requestSpec;
    private ClientHelper clientHelper;

    @BeforeEach
    public void setup() {
        Utils.initializeRESTAssured();
        requestSpec = new RequestSpecBuilder().setContentType(ContentType.JSON).build();
        requestSpec.header("Authorization", "Basic " + Utils.loginIntoServerAndGetBase64EncodedAuthenticationKey());
        responseSpec = new ResponseSpecBuilder().expectStatusCode(200).build();
        clientHelper = new ClientHelper(requestSpec, responseSpec);
    }

    @Test
    public void testClientSearchWorks_WithLastnameText_WithPaging() {
        // given
        String lastname = Utils.randomStringGenerator("Client_LastName_", 5);
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        request1.setLastname(lastname);
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        request2.setLastname(lastname);
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        request3.setLastname(lastname);
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(lastname, 0, 1);
        // then
        assertThat(result.getTotalElements()).isEqualTo(3);
        assertThat(result.getNumberOfElements()).isEqualTo(1);
        assertThat(result.getTotalPages()).isEqualTo(3);
    }

    @Test
    public void testClientSearchWorks_WhenNoExternalIdForClients() {
        // given
        String lastname = Utils.randomStringGenerator("Client_LastName_", 5);
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        request1.setExternalId(null);
        request1.setLastname(lastname);
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        request2.setExternalId(null);
        request2.setLastname(lastname);
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        request3.setExternalId(null);
        request3.setLastname(lastname);
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(lastname, 0, 1);
        // then
        assertThat(result.getTotalElements()).isEqualTo(3);
        assertThat(result.getNumberOfElements()).isEqualTo(1);
        assertThat(result.getTotalPages()).isEqualTo(3);
    }

    @Test
    public void testClientSearchWorks_WithLastnameTextOnDefaultOrdering() {
        // given
        String lastname = Utils.randomStringGenerator("Client_LastName_", 5);
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        request1.setLastname(lastname);
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        request2.setLastname(lastname);
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        request3.setLastname(lastname);
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(lastname);
        // then
        assertThat(result.getTotalElements()).isEqualTo(3);
        assertThat(result.getContent().get(0).getExternalId().getValue()).isEqualTo(request3.getExternalId());
        assertThat(result.getContent().get(1).getExternalId().getValue()).isEqualTo(request2.getExternalId());
        assertThat(result.getContent().get(2).getExternalId().getValue()).isEqualTo(request1.getExternalId());
    }

    @Test
    public void testClientSearchWorks_WithLastnameText_OrderedByIdAsc() {
        // given
        String lastname = Utils.randomStringGenerator("Client_LastName_", 5);
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        request1.setLastname(lastname);
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        request2.setLastname(lastname);
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        request3.setLastname(lastname);
        clientHelper.createClient(request3);

        SortOrder sortOrder = new SortOrder().property("id").direction(SortOrder.DirectionEnum.ASC);
        // when
        PageClientSearchData result = clientHelper.searchClients(lastname, sortOrder);
        // then
        assertThat(result.getTotalElements()).isEqualTo(3);
        assertThat(result.getContent().get(0).getExternalId().getValue()).isEqualTo(request1.getExternalId());
        assertThat(result.getContent().get(1).getExternalId().getValue()).isEqualTo(request2.getExternalId());
        assertThat(result.getContent().get(2).getExternalId().getValue()).isEqualTo(request3.getExternalId());
    }

    @Test
    public void testClientSearchWorks_ByExternalId() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(request2.getExternalId());
        // then
        assertThat(result.getTotalElements()).isEqualTo(1);
        assertThat(result.getContent().get(0).getExternalId().getValue()).isEqualTo(request2.getExternalId());
    }

    @Test
    public void testClientSearchWorks_ByAccountNumber() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        PostClientsResponse response2 = clientHelper.createClient(request2);
        GetClientsClientIdResponse client2Data = ClientHelper.getClient(requestSpec, responseSpec,
                Math.toIntExact(response2.getClientId()));

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(client2Data.getAccountNo());
        // then
        assertThat(result.getTotalElements()).isEqualTo(1);
        assertThat(result.getContent().get(0).getAccountNumber()).isEqualTo(client2Data.getAccountNo());
    }

    @Test
    public void testClientSearchWorks_ByDisplayName() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request2);
        String client2DisplayName = "%s %s".formatted(request2.getFirstname(), request2.getLastname());

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(client2DisplayName);
        // then
        assertThat(result.getTotalElements()).isEqualTo(1);
        assertThat(result.getContent().get(0).getDisplayName()).isEqualTo(client2DisplayName);
    }

    @Test
    public void testClientSearchWorks_ByMobileNo() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        request2.setMobileNo(Utils.randomNumberGenerator(8).toString());
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(request2.getMobileNo());
        // then
        assertThat(result.getTotalElements()).isEqualTo(1);
        assertThat(result.getContent().get(0).getMobileNo()).isEqualTo(request2.getMobileNo());
    }

    @Test
    public void testClientSearchDoesntReturnAnything_ByMobileNo() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request1);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(Utils.randomNumberGenerator(8).toString());
        // then
        assertThat(result.getTotalElements()).isEqualTo(0);
        assertThat(result.getContent()).isEmpty();
    }

    @Test
    public void testClientSearchWorks_ByClientIdentifier() {
        // given
        PostClientsRequest request1 = ClientHelper.defaultClientCreationRequest();
        request1.setMobileNo(Utils.randomNumberGenerator(8).toString());
        PostClientsResponse clientResponse = clientHelper.createClient(request1);
        final Long documentType = 1L;
        PostClientsClientIdIdentifiersRequest identifierRequest = ClientHelper.createClientIdentifer(documentType);
        final String documentKey = identifierRequest.getDocumentKey();
        PostClientsClientIdIdentifiersResponse clientIdentifierResponse = clientHelper.createClientIdentifer(clientResponse.getClientId(),
                identifierRequest);

        PostClientsRequest request2 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request2);

        PostClientsRequest request3 = ClientHelper.defaultClientCreationRequest();
        clientHelper.createClient(request3);
        // when
        PageClientSearchData result = clientHelper.searchClients(documentKey);
        // then
        assertThat(result.getTotalElements()).isEqualTo(1);
        assertThat(result.getContent().get(0).getMobileNo()).isEqualTo(request1.getMobileNo());
    }

    @Test
    public void testClientSearchByLegalForm() {
        // given
        PostOfficesResponse newOffice = ok(
                fineractClient().offices.createOffice(new PostOfficesRequest().name(Utils.randomStringGenerator("TestOffice_", 6))
                        .parentId(1L).openingDate(LocalDate.of(1970, 1, 1)).dateFormat("yyyy-MM-dd").locale("en_US")));
        PostClientsRequest individualClientRequest = ClientHelper.defaultClientCreationRequest();
        individualClientRequest.setLegalFormId(1L);
        individualClientRequest.setOfficeId(newOffice.getOfficeId());
        PostClientsResponse individualClientResponse = clientHelper.createClient(individualClientRequest);

        PostClientsRequest entityClientRequest = ClientHelper.defaultClientCreationRequest();
        entityClientRequest.setOfficeId(newOffice.getOfficeId());
        entityClientRequest.setLegalFormId(2L);
        PostClientsResponse entityClientResponse = clientHelper.createClient(entityClientRequest);

        PostClientsRequest secondEntityClientRequest = ClientHelper.defaultClientCreationRequest();
        secondEntityClientRequest.setOfficeId(newOffice.getOfficeId());
        secondEntityClientRequest.setLegalFormId(2L);
        PostClientsResponse secondEntityClientResponse = clientHelper.createClient(secondEntityClientRequest);
        // when
        GetClientsResponse individualClients = ok(fineractClient().clients.retrieveAll21(newOffice.getOfficeId(), null, null, null, null,
                null, null, null, null, null, null, null, 1));
        GetClientsResponse entityClients = ok(fineractClient().clients.retrieveAll21(newOffice.getOfficeId(), null, null, null, null, null,
                null, null, null, "id", null, null, 2));
        // then
        assertThat(individualClients.getTotalFilteredRecords()).isEqualTo(1);
        assertThat(individualClients.getPageItems().get(0).getId()).isEqualTo(individualClientResponse.getClientId());
        assertThat(entityClients.getTotalFilteredRecords()).isEqualTo(2);
        assertThat(entityClients.getPageItems().get(0).getId()).isEqualTo(entityClientResponse.getClientId());
        assertThat(entityClients.getPageItems().get(1).getId()).isEqualTo(secondEntityClientResponse.getClientId());
    }

    @Test
    public void testClientSearchOptions_ContainsOfficesAndTags() {
        String json = clientHelper.retrieveSearchOptionsJson();
        JsonPath path = JsonPath.from(json);
        assertThat(path.getList("offices")).isNotEmpty();
        assertThat(path.getList("tags")).isNotEmpty();
        assertThat(path.getList("promoters")).isNotNull();
        assertThat(path.getList("gestores")).isNotNull();
    }

    @Test
    public void testClientSearch_EmptyTextWithOfficeFilter_ReturnsClientsInOffice() {
        PostOfficesResponse newOffice = ok(
                fineractClient().offices.createOffice(new PostOfficesRequest().name(Utils.randomStringGenerator("FilterOffice_", 6))
                        .parentId(1L).openingDate(LocalDate.of(1970, 1, 1)).dateFormat("yyyy-MM-dd").locale("en_US")));
        String lastname = Utils.randomStringGenerator("Filter_LastName_", 5);
        PostClientsRequest inOffice = ClientHelper.defaultClientCreationRequest().lastname(lastname).officeId(newOffice.getOfficeId());
        PostClientsResponse inOfficeResponse = clientHelper.createClient(inOffice);
        PostClientsRequest otherOffice = ClientHelper.defaultClientCreationRequest().lastname(lastname);
        clientHelper.createClient(otherOffice);

        Map<String, Object> filters = new HashMap<>();
        filters.put("officeId", newOffice.getOfficeId());
        String json = clientHelper.searchClientsJson(filters, 0, 50);
        JsonPath path = JsonPath.from(json);
        assertThat(path.getLong("totalElements")).isEqualTo(1L);
        assertThat(path.getLong("content[0].id")).isEqualTo(inOfficeResponse.getClientId());
    }

    @Test
    public void testClientSearch_FilterByStatus() {
        String lastname = Utils.randomStringGenerator("Status_LastName_", 5);
        PostClientsRequest activeRequest = ClientHelper.defaultClientCreationRequest().lastname(lastname);
        PostClientsResponse activeResponse = clientHelper.createClient(activeRequest);

        Map<String, Object> activeFilters = new HashMap<>();
        activeFilters.put("text", lastname);
        activeFilters.put("status", "ACTIVE");
        JsonPath activePath = JsonPath.from(clientHelper.searchClientsJson(activeFilters, 0, 50));
        assertThat(activePath.getLong("totalElements")).isEqualTo(1L);
        assertThat(activePath.getLong("content[0].id")).isEqualTo(activeResponse.getClientId());

        Map<String, Object> pendingFilters = new HashMap<>();
        pendingFilters.put("text", lastname);
        pendingFilters.put("status", "PENDING");
        JsonPath pendingPath = JsonPath.from(clientHelper.searchClientsJson(pendingFilters, 0, 50));
        assertThat(pendingPath.getLong("totalElements")).isEqualTo(0L);
    }

    @Test
    @SuppressWarnings("unchecked")
    public void testClientSearch_FilterByTag() {
        String lastname = Utils.randomStringGenerator("Tag_LastName_", 5);
        PostClientsResponse tagged = clientHelper.createClient(ClientHelper.defaultClientCreationRequest().lastname(lastname));
        PostClientsResponse untagged = clientHelper.createClient(ClientHelper.defaultClientCreationRequest().lastname(lastname));

        Map<String, Object> template = JsonPath.from(
                Utils.performServerGet(requestSpec, responseSpec, "/fineract-provider/api/v1/clients/template?" + Utils.TENANT_IDENTIFIER))
                .getMap("$");
        List<Map<String, Object>> tags = (List<Map<String, Object>>) template.get("tagOptions");
        assertThat(tags).isNotEmpty();
        Number tagId = (Number) tags.get(0).get("id");

        Utils.performServerPut(requestSpec, responseSpec,
                "/fineract-provider/api/v1/clients/" + tagged.getClientId() + "?" + Utils.TENANT_IDENTIFIER,
                "{\"tagIds\":[" + tagId.longValue() + "]}");

        Map<String, Object> filters = new HashMap<>();
        filters.put("text", lastname);
        filters.put("tagId", tagId.longValue());
        JsonPath path = JsonPath.from(clientHelper.searchClientsJson(filters, 0, 50));
        assertThat(path.getLong("totalElements")).isEqualTo(1L);
        assertThat(path.getLong("content[0].id")).isEqualTo(tagged.getClientId());
        assertThat(path.getLong("content[0].id")).isNotEqualTo(untagged.getClientId());
    }

    @Test
    public void testClientSearch_FilterByPromoterAndGestorFromMigration289() {
        String lastname = Utils.randomStringGenerator("Staff_LastName_", 5);
        PostClientsResponse promoterClient = clientHelper.createClient(ClientHelper.defaultClientCreationRequest().lastname(lastname));
        PostClientsResponse gestorClient = clientHelper.createClient(ClientHelper.defaultClientCreationRequest().lastname(lastname));
        Integer promoterStaffId = StaffHelper.createStaff(requestSpec, responseSpec);
        Integer gestorStaffId = StaffHelper.createStaff(requestSpec, responseSpec);

        DatatableHelper datatableHelper = new DatatableHelper(requestSpec, responseSpec);
        datatableHelper.createDatatableEntry("credesal_client_staff_assignment", promoterClient.getClientId().intValue(), false,
                assignmentJson(promoterStaffId, null));
        datatableHelper.createDatatableEntry("credesal_client_staff_assignment", gestorClient.getClientId().intValue(), false,
                assignmentJson(null, gestorStaffId));

        Map<String, Object> promoterFilters = new HashMap<>();
        promoterFilters.put("text", lastname);
        promoterFilters.put("promoterStaffId", promoterStaffId.longValue());
        JsonPath promoterPath = JsonPath.from(clientHelper.searchClientsJson(promoterFilters, 0, 50));
        assertThat(promoterPath.getLong("totalElements")).isEqualTo(1L);
        assertThat(promoterPath.getLong("content[0].id")).isEqualTo(promoterClient.getClientId());

        Map<String, Object> gestorFilters = new HashMap<>();
        gestorFilters.put("text", lastname);
        gestorFilters.put("gestorStaffId", gestorStaffId.longValue());
        JsonPath gestorPath = JsonPath.from(clientHelper.searchClientsJson(gestorFilters, 0, 50));
        assertThat(gestorPath.getLong("totalElements")).isEqualTo(1L);
        assertThat(gestorPath.getLong("content[0].id")).isEqualTo(gestorClient.getClientId());

        Map<String, Object> combined = new HashMap<>();
        combined.put("text", lastname);
        combined.put("promoterStaffId", promoterStaffId.longValue());
        combined.put("gestorStaffId", gestorStaffId.longValue());
        JsonPath combinedPath = JsonPath.from(clientHelper.searchClientsJson(combined, 0, 50));
        assertThat(combinedPath.getLong("totalElements")).isEqualTo(0L);

        String optionsJson = clientHelper.retrieveSearchOptionsJson();
        List<Number> promoterIds = JsonPath.from(optionsJson).getList("promoters.id");
        List<Number> gestorIds = JsonPath.from(optionsJson).getList("gestores.id");
        Assertions.assertThat(promoterIds.stream().map(Number::longValue).toList()).contains(promoterStaffId.longValue());
        Assertions.assertThat(gestorIds.stream().map(Number::longValue).toList()).contains(gestorStaffId.longValue());
    }

    @Test
    public void testClientSearchOptions_PromotersAndGestoresScopedToOffice() {
        PostOfficesResponse otherOffice = ok(
                fineractClient().offices.createOffice(new PostOfficesRequest().name(Utils.randomStringGenerator("StaffOffice_", 6))
                        .parentId(1L).openingDate(LocalDate.of(1970, 1, 1)).dateFormat("yyyy-MM-dd").locale("en_US")));
        PostClientsResponse headOfficeClient = clientHelper.createClient(ClientHelper.defaultClientCreationRequest());
        PostClientsResponse otherOfficeClient = clientHelper
                .createClient(ClientHelper.defaultClientCreationRequest().officeId(otherOffice.getOfficeId()));

        Integer headOfficeStaff = StaffHelper.createStaff(requestSpec, responseSpec);
        Map<String, Object> otherStaffPayload = StaffHelper.getMapWithJoiningDate();
        otherStaffPayload.put("officeId", otherOffice.getOfficeId());
        otherStaffPayload.put("firstname", Utils.uniqueRandomStringGenerator("other_", 5));
        otherStaffPayload.put("lastname", Utils.uniqueRandomStringGenerator("Staff_", 4));
        otherStaffPayload.put("isLoanOfficer", true);
        Integer otherOfficeStaff = (Integer) StaffHelper
                .createStaffWithJson(requestSpec, responseSpec, new com.google.gson.Gson().toJson(otherStaffPayload)).get("resourceId");

        DatatableHelper datatableHelper = new DatatableHelper(requestSpec, responseSpec);
        datatableHelper.createDatatableEntry("credesal_client_staff_assignment", headOfficeClient.getClientId().intValue(), false,
                assignmentJson(headOfficeStaff, null));
        datatableHelper.createDatatableEntry("credesal_client_staff_assignment", otherOfficeClient.getClientId().intValue(), false,
                assignmentJson(otherOfficeStaff, null));

        List<Long> allPromoters = JsonPath.from(clientHelper.retrieveSearchOptionsJson()).getList("promoters.id", Long.class);
        Assertions.assertThat(allPromoters).contains(headOfficeStaff.longValue(), otherOfficeStaff.longValue());

        List<Long> headOfficePromoters = JsonPath.from(clientHelper.retrieveSearchOptionsJson(1L)).getList("promoters.id", Long.class);
        Assertions.assertThat(headOfficePromoters).contains(headOfficeStaff.longValue());
        Assertions.assertThat(headOfficePromoters).doesNotContain(otherOfficeStaff.longValue());

        List<Long> otherOfficePromoters = JsonPath.from(clientHelper.retrieveSearchOptionsJson(otherOffice.getOfficeId()))
                .getList("promoters.id", Long.class);
        Assertions.assertThat(otherOfficePromoters).contains(otherOfficeStaff.longValue());
        Assertions.assertThat(otherOfficePromoters).doesNotContain(headOfficeStaff.longValue());
    }

    private String assignmentJson(Integer promoterStaffId, Integer gestorStaffId) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("locale", "en");
        payload.put("dateFormat", "dd MMMM yyyy");
        if (promoterStaffId != null) {
            payload.put("promoter_staff_id", promoterStaffId);
        }
        if (gestorStaffId != null) {
            payload.put("collections_manager_staff_id", gestorStaffId);
        }
        return new com.google.gson.Gson().toJson(payload);
    }

}
