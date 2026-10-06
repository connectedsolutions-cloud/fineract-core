package org.apache.fineract.portfolio.treasury.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.treasury.domain.TreasuryBankAccount;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovement;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLine;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLink;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementLinkRepository;
import org.apache.fineract.portfolio.treasury.domain.TreasuryMovementRepository;
import org.apache.fineract.portfolio.treasury.service.JournalReferenceNumberService;
import org.apache.fineract.portfolio.treasury.service.TreasuryBankAccountService;
import org.apache.fineract.portfolio.treasury.service.TreasuryMovementCommand;
import org.apache.fineract.portfolio.treasury.service.TreasuryMovementService;
import org.apache.fineract.portfolio.treasury.service.TreasuryProductLinkService;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Path("/v1/treasury")
@Component
@RequiredArgsConstructor
public class TreasuryApiResource {

    private final PlatformSecurityContext context;
    private final FromJsonHelper jsonHelper;
    private final TreasuryBankAccountService bankAccountService;
    private final TreasuryMovementService movementService;
    private final JournalReferenceNumberService journalReferenceNumberService;
    private final TreasuryProductLinkService productLinkService;
    private final TreasuryMovementRepository movementRepository;
    private final TreasuryMovementLinkRepository linkRepository;

    @POST
    @Path("journalnumbers/seed-imported")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> seedImportedJournalNumbers(String body) {
        context.authenticatedUser().validateHasPermissionTo("IMPORT_ARISSTO_HISTORICAL_GL");
        var json = jsonHelper.parse(body).getAsJsonObject();
        LocalDate cutoffDate = jsonHelper.extractLocalDateNamed("cutoffDate", json);
        var sourceJson = json.getAsJsonObject("sourceMaxima");
        if (sourceJson == null || sourceJson.entrySet().isEmpty()) {
            throw new IllegalArgumentException("A frozen Arissto journal-number highwater is required");
        }
        Map<String, Integer> sourceMaxima = new LinkedHashMap<>();
        sourceJson.entrySet().forEach(entry -> sourceMaxima.put(entry.getKey(), entry.getValue().getAsInt()));
        return journalReferenceNumberService.seedImported(cutoffDate, sourceMaxima);
    }

    @GET
    @Path("bankaccounts")
    @Produces(MediaType.APPLICATION_JSON)
    @Transactional(readOnly = true)
    public List<Map<String, Object>> listBanks(@QueryParam("picker") Boolean picker) {
        if (Boolean.TRUE.equals(picker)) {
            context.authenticatedUser();
            return bankAccountService.list(true).stream().map(this::bankPicker).toList();
        }
        context.authenticatedUser().validateHasReadPermission("TREASURY");
        return bankAccountService.list(false).stream().map(this::bankDetail).toList();
    }

    @GET
    @Path("bankaccounts/match")
    @Produces(MediaType.APPLICATION_JSON)
    @Transactional(readOnly = true)
    public Map<String, Object> matchBank(@QueryParam("productType") String productType, @QueryParam("productId") Long productId,
            @QueryParam("paymentTypeId") Long paymentTypeId) {
        context.authenticatedUser();
        return productLinkService.matchBank(productType, productId, paymentTypeId);
    }

    @POST
    @Path("bankaccounts")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> createBank(String body) {
        context.authenticatedUser().validateHasCreatePermission("TREASURY_BANKACCOUNT");
        var json = jsonHelper.parse(body).getAsJsonObject();
        TreasuryBankAccount bank = bankAccountService.create(jsonHelper.extractStringNamed("name", json),
                jsonHelper.extractLongNamed("glAccountId", json), jsonHelper.extractStringNamed("currencyCode", json),
                json.has("officeId") ? jsonHelper.extractLongNamed("officeId", json) : null,
                json.has("externalAccountReference") ? jsonHelper.extractStringNamed("externalAccountReference", json) : null,
                json.has("alias") ? jsonHelper.extractStringNamed("alias", json) : null);
        return bankDetail(bank);
    }

    @PUT
    @Path("bankaccounts/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> updateBank(@PathParam("id") Long id, String body) {
        context.authenticatedUser().validateHasCreatePermission("TREASURY_BANKACCOUNT");
        var json = jsonHelper.parse(body).getAsJsonObject();
        Boolean active = json.has("active") ? json.get("active").getAsBoolean() : null;
        TreasuryBankAccount bank = bankAccountService.update(id, json.has("name") ? jsonHelper.extractStringNamed("name", json) : null,
                json.has("officeId") ? jsonHelper.extractLongNamed("officeId", json) : null,
                json.has("externalAccountReference") ? jsonHelper.extractStringNamed("externalAccountReference", json) : null,
                json.has("alias") ? jsonHelper.extractStringNamed("alias", json) : null, active);
        return bankDetail(bank);
    }

    @GET
    @Path("bankaccounts/{id}/movements")
    @Produces({ MediaType.APPLICATION_JSON, "text/csv" })
    @Transactional(readOnly = true)
    public Response movements(@PathParam("id") Long id, @QueryParam("type") String type, @QueryParam("payee") String payee,
            @QueryParam("fromDate") String fromDate, @QueryParam("toDate") String toDate, @QueryParam("export") String export) {
        context.authenticatedUser().validateHasReadPermission("TREASURY");
        List<Map<String, Object>> rows = filterMovements(id, type, payee, fromDate, toDate);
        if ("csv".equalsIgnoreCase(export)) {
            return Response.ok(toCsv(rows), "text/csv").header("Content-Disposition", "attachment; filename=treasury-movements.csv")
                    .build();
        }
        return Response.ok(rows).build();
    }

    @POST
    @Path("movements")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> createMovement(String body) {
        context.authenticatedUser().validateHasCreatePermission("TREASURY_MOVEMENT");
        var json = jsonHelper.parse(body).getAsJsonObject();
        TreasuryMovement movement = movementService.post(new TreasuryMovementCommand(jsonHelper.extractStringNamed("type", json),
                jsonHelper.extractLocalDateNamed("businessDate", json),
                json.has("valueDate") ? jsonHelper.extractLocalDateNamed("valueDate", json) : null,
                jsonHelper.extractLongNamed("officeId", json), jsonHelper.extractBigDecimalWithLocaleNamed("amount", json),
                json.has("direction") ? jsonHelper.extractStringNamed("direction", json) : null,
                json.has("bankAccountId") ? jsonHelper.extractLongNamed("bankAccountId", json) : null,
                json.has("destinationBankAccountId") ? jsonHelper.extractLongNamed("destinationBankAccountId", json) : null,
                json.has("counterGlAccountId") ? jsonHelper.extractLongNamed("counterGlAccountId", json) : null,
                json.has("bankReference") ? jsonHelper.extractStringNamed("bankReference", json) : null,
                json.has("payeeName") ? jsonHelper.extractStringNamed("payeeName", json) : null,
                json.has("staffId") ? jsonHelper.extractLongNamed("staffId", json) : null,
                json.has("note") ? jsonHelper.extractStringNamed("note", json) : null));
        return movementDetail(movement);
    }

    @POST
    @Path("movements/{id}")
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> reverse(@PathParam("id") Long id, @QueryParam("command") String command) {
        context.authenticatedUser().validateHasPermissionTo("REVERSE_TREASURY_MOVEMENT");
        if (!"reverse".equals(command)) {
            throw TreasuryMovementService.rule("error.msg.treasury.command.invalid", "Supported command is reverse");
        }
        return movementDetail(movementService.reverse(id));
    }

    @GET
    @Path("links")
    @Produces(MediaType.APPLICATION_JSON)
    @Transactional(readOnly = true)
    public Map<String, Object> link(@QueryParam("linkType") String linkType, @QueryParam("entityId") Long entityId) {
        context.authenticatedUser().validateHasReadPermission("TREASURY");
        TreasuryMovementLink link = linkRepository.findByLinkTypeAndEntityId(linkType, entityId).orElse(null);
        if (link == null) {
            return Map.of();
        }
        return movementDetail(link.getMovement());
    }

    private List<Map<String, Object>> filterMovements(Long bankId, String type, String payee, String fromDate, String toDate) {
        LocalDate from = StringUtils.isBlank(fromDate) ? null : LocalDate.parse(fromDate);
        LocalDate to = StringUtils.isBlank(toDate) ? null : LocalDate.parse(toDate);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (TreasuryMovement movement : movementRepository.findForBank(bankId)) {
            if (StringUtils.isNotBlank(type) && !type.equals(movement.getMovementType())) {
                continue;
            }
            if (StringUtils.isNotBlank(payee)
                    && (movement.getPayeeName() == null || !movement.getPayeeName().toLowerCase().contains(payee.toLowerCase()))) {
                continue;
            }
            if (from != null && movement.getBusinessDate().isBefore(from)) {
                continue;
            }
            if (to != null && movement.getBusinessDate().isAfter(to)) {
                continue;
            }
            rows.add(movementDetail(movement));
        }
        return rows;
    }

    private Map<String, Object> bankPicker(TreasuryBankAccount bank) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", bank.getId());
        data.put("name", bank.getName());
        data.put("alias", bank.getAlias());
        data.put("externalAccountReference", bank.getExternalAccountReference());
        data.put("currencyCode", bank.getCurrencyCode());
        data.put("glAccountId", bank.getGlAccount().getId());
        return data;
    }

    private Map<String, Object> bankDetail(TreasuryBankAccount bank) {
        Map<String, Object> data = bankPicker(bank);
        data.put("active", bank.isActive());
        data.put("balance", bank.getBalance());
        data.put("officeId", bank.getOffice() == null ? null : bank.getOffice().getId());
        data.put("glCode", bank.getGlAccount().getGlCode());
        return data;
    }

    private Map<String, Object> movementDetail(TreasuryMovement movement) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", movement.getId());
        data.put("type", movement.getMovementType());
        data.put("status", movement.getStatus());
        data.put("businessDate", movement.getBusinessDate());
        data.put("valueDate", movement.getValueDate());
        data.put("amount", movement.getAmount());
        data.put("currencyCode", movement.getCurrencyCode());
        data.put("journalOwner", movement.getJournalOwner());
        data.put("journalTransactionId", movement.getJournalTransactionId());
        data.put("refNum", movement.getRefNum());
        data.put("bankReference", movement.getBankReference());
        data.put("payeeName", movement.getPayeeName());
        data.put("note", movement.getNote());
        data.put("officeId", movement.getOffice() == null ? null : movement.getOffice().getId());
        List<Map<String, Object>> lines = new ArrayList<>();
        for (TreasuryMovementLine line : movement.getLines()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("bankAccountId", line.getBankAccount().getId());
            row.put("bankName", line.getBankAccount().getName());
            row.put("direction", line.getDirection());
            row.put("amount", line.getAmount());
            row.put("balanceAfter", line.getBalanceAfter());
            lines.add(row);
        }
        data.put("lines", lines);
        List<Map<String, Object>> links = new ArrayList<>();
        for (TreasuryMovementLink link : movement.getLinks()) {
            links.add(Map.of("linkType", link.getLinkType(), "entityId", link.getEntityId()));
        }
        data.put("links", links);
        return data;
    }

    private String toCsv(List<Map<String, Object>> rows) {
        StringBuilder csv = new StringBuilder("date,valueDate,type,status,debit,credit,payee,bankReference,balance,refNum,journal\n");
        for (Map<String, Object> row : rows) {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> lines = (List<Map<String, Object>>) row.get("lines");
            if (lines == null || lines.isEmpty()) {
                continue;
            }
            for (Map<String, Object> line : lines) {
                boolean debit = "debit".equals(line.get("direction"));
                BigDecimal amount = (BigDecimal) line.get("amount");
                csv.append(row.get("businessDate")).append(',').append(row.get("valueDate")).append(',').append(row.get("type")).append(',')
                        .append(row.get("status")).append(',').append(debit ? amount : "").append(',').append(debit ? "" : amount)
                        .append(',').append(csvValue(row.get("payeeName"))).append(',').append(csvValue(row.get("bankReference")))
                        .append(',').append(line.get("balanceAfter")).append(',').append(csvValue(row.get("refNum"))).append(',')
                        .append(csvValue(row.get("journalTransactionId"))).append('\n');
            }
        }
        return csv.toString();
    }

    private String csvValue(Object value) {
        if (value == null) {
            return "";
        }
        String text = String.valueOf(value).replace("\"", "\"\"");
        return text.contains(",") ? "\"" + text + "\"" : text;
    }
}
