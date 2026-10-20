package org.apache.fineract.portfolio.treasury.api;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Read-only view of imported cheque facts; source identities never leave this API. */
@Path("/v1/cheques/history")
@Component
@RequiredArgsConstructor
public class HistoricalChequeApiResource {

    private final PlatformSecurityContext context;
    private final NamedParameterJdbcTemplate jdbc;

    @GET
    @Produces({ MediaType.APPLICATION_JSON, "text/csv" })
    @Transactional(readOnly = true)
    public Response list(@QueryParam("number") String number, @QueryParam("exact") Boolean exact,
            @QueryParam("bank") String bank, @QueryParam("kind") String kind,
            @QueryParam("fromDate") String fromDate, @QueryParam("toDate") String toDate,
            @QueryParam("amount") BigDecimal amount, @QueryParam("limit") Integer limit,
            @QueryParam("sort") String sort, @QueryParam("order") String order,
            @QueryParam("export") String export) {
        context.authenticatedUser().validateHasReadPermission("TREASURY");
        if (kind != null && !kind.isBlank() && !kind.equals("issued") && !kind.equals("received")) {
            throw new IllegalArgumentException("Cheque kind must be issued or received");
        }
        boolean csvExport = "csv".equalsIgnoreCase(export);
        int maximum = csvExport ? 50000 : 1000;
        if (limit != null && (limit < 1 || limit > maximum)) {
            throw new IllegalArgumentException("Cheque history limit is out of range");
        }
        StringBuilder sql = new StringBuilder("""
                SELECT id,source_kind,cheque_number,bank_name,amount,cheque_date,cancelled
                  FROM credesal_historical_cheque WHERE 1=1
                """);
        MapSqlParameterSource args = new MapSqlParameterSource();
        if (number != null && !number.isBlank()) {
            if (Boolean.TRUE.equals(exact)) {
                sql.append(" AND cheque_number=:number");
            } else {
                sql.append(" AND POSITION(LOWER(:number) IN LOWER(COALESCE(cheque_number,'')))>0");
            }
            args.addValue("number", number.trim());
        }
        if (bank != null && !bank.isBlank()) {
            sql.append(" AND POSITION(LOWER(:bank) IN LOWER(bank_name))>0");
            args.addValue("bank", bank.trim());
        }
        if (kind != null && !kind.isBlank()) {
            sql.append(" AND source_kind=:kind");
            args.addValue("kind", kind);
        }
        if (fromDate != null && !fromDate.isBlank()) {
            sql.append(" AND cheque_date>=:fromDate");
            args.addValue("fromDate", LocalDate.parse(fromDate));
        }
        if (toDate != null && !toDate.isBlank()) {
            sql.append(" AND cheque_date<=:toDate");
            args.addValue("toDate", LocalDate.parse(toDate));
        }
        if (amount != null) {
            sql.append(" AND amount=:amount");
            args.addValue("amount", amount);
        }
        Map<String, String> sortable = Map.of("date", "cheque_date", "number", "cheque_number",
                "bank", "bank_name", "amount", "amount", "kind", "source_kind");
        String column = sort == null ? "cheque_date" : sortable.get(sort);
        if (sort != null && !sortable.containsKey(sort)) {
            throw new IllegalArgumentException("Unsupported cheque history sort column");
        }
        if (order != null && !order.equalsIgnoreCase("asc") && !order.equalsIgnoreCase("desc")) {
            throw new IllegalArgumentException("Cheque history order must be asc or desc");
        }
        sql.append(" ORDER BY ").append(column).append(" ")
                .append("asc".equalsIgnoreCase(order) ? "ASC" : "DESC")
                .append(" NULLS LAST,id DESC LIMIT :limit");
        args.addValue("limit", limit == null ? (csvExport ? maximum : 200) : limit);
        List<Map<String, Object>> rows = jdbc.query(sql.toString(), args, (rs, rowNum) -> cheque(rs));
        attachLinks(rows);
        if (csvExport) {
            return Response.ok(csv(rows), "text/csv")
                    .header("Content-Disposition", "attachment; filename=historical-cheques.csv").build();
        }
        return Response.ok(rows).build();
    }

    @GET
    @Path("{id}")
    @Produces(MediaType.APPLICATION_JSON)
    @Transactional(readOnly = true)
    public Map<String, Object> one(@PathParam("id") Long id) {
        context.authenticatedUser().validateHasReadPermission("TREASURY");
        List<Map<String, Object>> rows = jdbc.query("""
                SELECT id,source_kind,cheque_number,bank_name,amount,cheque_date,cancelled
                  FROM credesal_historical_cheque WHERE id=:id
                """, new MapSqlParameterSource("id", id), (rs, rowNum) -> cheque(rs));
        if (rows.isEmpty()) {
            throw new WebApplicationException("Historical cheque not found", 404);
        }
        attachLinks(rows);
        return rows.get(0);
    }

    private Map<String, Object> cheque(ResultSet rs) throws SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", rs.getLong("id"));
        row.put("kind", rs.getString("source_kind"));
        row.put("chequeNumber", rs.getString("cheque_number"));
        row.put("bank", rs.getString("bank_name"));
        row.put("amount", rs.getBigDecimal("amount"));
        var date = rs.getDate("cheque_date");
        row.put("date", date == null ? null : date.toLocalDate());
        Object cancelled = rs.getObject("cancelled");
        row.put("cancelled", cancelled == null ? null : rs.getBoolean("cancelled"));
        return row;
    }

    private void attachLinks(List<Map<String, Object>> rows) {
        if (rows.isEmpty()) {
            return;
        }
        List<Long> ids = rows.stream().map(row -> (Long) row.get("id")).toList();
        Map<Long, List<Map<String, Object>>> links = new HashMap<>();
        jdbc.query("""
                SELECT cheque_id,relationship_type,target_type,target_id
                  FROM credesal_historical_cheque_link
                 WHERE cheque_id IN (:ids) ORDER BY relationship_type,target_id NULLS LAST
                """, new MapSqlParameterSource("ids", ids), rs -> {
                    Map<String, Object> link = new LinkedHashMap<>();
                    link.put("relationship", rs.getString("relationship_type"));
                    link.put("targetType", rs.getString("target_type"));
                    link.put("targetId", rs.getString("target_id"));
                    links.computeIfAbsent(rs.getLong("cheque_id"), ignored -> new ArrayList<>()).add(link);
                });
        rows.forEach(row -> row.put("links", links.getOrDefault((Long) row.get("id"), List.of())));
    }

    private String csv(List<Map<String, Object>> rows) {
        StringBuilder out = new StringBuilder("kind,cheque_number,bank,amount,date,cancelled,relationships\n");
        for (Map<String, Object> row : rows) {
            for (String key : List.of("kind", "chequeNumber", "bank", "amount", "date", "cancelled")) {
                out.append(quoted(row.get(key))).append(',');
            }
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> links = (List<Map<String, Object>>) row.get("links");
            out.append(quoted(links.stream().map(link -> String.valueOf(link.get("relationship"))).distinct().toList().toString()));
            out.append('\n');
        }
        return out.toString();
    }

    private String quoted(Object value) {
        String text = value == null ? "" : String.valueOf(value);
        return '"' + text.replace("\"", "\"\"") + '"';
    }
}
