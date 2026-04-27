package org.apache.fineract.portfolio.invoice.mh;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Component
public class MhValidationFirmaRestClient {

    private static final String HEADER_SIGNING_API_KEY = "X-Signing-API-Key";
    private static final String HEADER_FIRMA_SECRET = "X-Firma-Secret";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${mh.validation.base-url:http://localhost:8113/firma}")
    private String baseUrl;

    @Value("${mh.validation.path:/validardocumento/?sync=false}")
    private String validationPath;

    public MhSubmitResult submitValidate(Map<String, Object> dteJson, MhFirmaCredentials credentials) {
        String url = trimTrailingSlash(baseUrl) + (validationPath.startsWith("/") ? validationPath : "/" + validationPath);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("nit", credentials.nitFourteenDigits());
        body.put("passwordPri", credentials.passwordPri());
        body.put("dteJson", dteJson);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (StringUtils.isNotBlank(credentials.signingApiKey())) {
            headers.add(HEADER_SIGNING_API_KEY, credentials.signingApiKey());
        }
        if (StringUtils.isNotBlank(credentials.firmaSecret())) {
            headers.add(HEADER_FIRMA_SECRET, credentials.firmaSecret());
        }

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
        try {
            ResponseEntity<String> response = restTemplate.exchange(url, HttpMethod.POST, entity, String.class);
            return parseResponse(response.getStatusCode().value(), response.getBody());
        } catch (HttpStatusCodeException e) {
            log.warn("MH validation HTTP error status={} body={}", e.getStatusCode().value(), e.getResponseBodyAsString());
            return MhSubmitResult.error("HTTP " + e.getStatusCode().value() + ": " + e.getResponseBodyAsString());
        } catch (Exception e) {
            log.error("MH validation call failed", e);
            return MhSubmitResult.error(e.getMessage());
        }
    }

    private MhSubmitResult parseResponse(int status, String rawBody) {
        if (rawBody == null || rawBody.isBlank()) {
            return MhSubmitResult.error("Empty response body");
        }
        try {
            JsonNode root = objectMapper.readTree(rawBody);
            String st = root.path("status").asText("");
            if ("ERROR".equalsIgnoreCase(st)) {
                String msg = extractMensaje(root.path("body"));
                return MhSubmitResult.error(msg);
            }
            if (!"OK".equalsIgnoreCase(st)) {
                return MhSubmitResult.error("Unexpected status: " + st);
            }
            JsonNode body = root.path("body");
            if (status == 202 && body.hasNonNull("jobId")) {
                return MhSubmitResult.accepted(body.get("jobId").asText());
            }
            if (body.isTextual()) {
                return MhSubmitResult.syncOk(body.asText());
            }
            if (body.hasNonNull("jobId")) {
                return MhSubmitResult.accepted(body.get("jobId").asText());
            }
            return MhSubmitResult.error("OK response without jobId");
        } catch (Exception e) {
            return MhSubmitResult.error("Invalid JSON: " + e.getMessage());
        }
    }

    private static String extractMensaje(JsonNode body) {
        JsonNode m = body.path("mensaje");
        if (m.isArray()) {
            StringBuilder sb = new StringBuilder();
            for (JsonNode n : m) {
                if (sb.length() > 0) {
                    sb.append("; ");
                }
                sb.append(n.asText());
            }
            return sb.toString();
        }
        return m.asText(body.path("codigo").asText("ERROR"));
    }

    private static String trimTrailingSlash(String u) {
        if (u == null) {
            return "";
        }
        return u.endsWith("/") ? u.substring(0, u.length() - 1) : u;
    }
}
