package org.apache.fineract.portfolio.invoice.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.Response;

@Service
@RequiredArgsConstructor
@Slf4j
public class InvoiceMhWebhookService {

    private final InvoiceRepository invoiceRepository;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Value("${mh.webhook.shared-secret:}")
    private String expectedWebhookSecret;

    public void validateHeaderSecret(String headerValue) {
        if (StringUtils.isBlank(expectedWebhookSecret)) {
            throw new IllegalStateException("mh.webhook.shared-secret is not configured");
        }
        if (!expectedWebhookSecret.equals(headerValue)) {
            throw new WebApplicationException(Response.status(Response.Status.UNAUTHORIZED).entity("Invalid X-Webhook-Secret").build());
        }
    }

    @Transactional
    public void handlePayload(String jsonBody) {
        if (StringUtils.isBlank(jsonBody)) {
            return;
        }
        try {
            JsonNode root = objectMapper.readTree(jsonBody);
            String eventType = root.path("eventType").asText("");
            if (!"mh.validation.result".equalsIgnoreCase(eventType)) {
                log.debug("Ignoring webhook eventType={}", eventType);
                return;
            }
            String codigo = firstNonBlank(textAt(root, "codigoGeneracion", "codigo_generacion"),
                    textAt(root.path("result"), "codigoGeneracion", "codigo_generacion"),
                    textAt(root.path("result").path("identificacion"), "codigoGeneracion", "codigo_generacion"));
            String numero = firstNonBlank(textAt(root, "numeroControl", "numero_control"),
                    textAt(root.path("result"), "numeroControl", "numero_control"),
                    textAt(root.path("result").path("identificacion"), "numeroControl", "numero_control"));
            if (StringUtils.isAnyBlank(codigo, numero)) {
                log.warn("MH webhook missing codigoGeneracion/numeroControl; jobId={}", root.path("jobId").asText(null));
                return;
            }
            Invoice invoice = invoiceRepository.findByCodigoGeneracionAndNumeroControl(codigo, numero).orElse(null);
            if (invoice == null) {
                log.warn("No invoice for codigoGeneracion={} numeroControl={}", codigo, numero);
                return;
            }
            if ("SUCCESS".equalsIgnoreCase(invoice.getMhValidationStatus())) {
                log.info("Duplicate MH webhook ignored for invoice id={}", invoice.getId());
                return;
            }
            LocalDateTime now = LocalDateTime.now();
            String status = root.path("status").asText("");
            if ("success".equalsIgnoreCase(status)) {
                JsonNode result = root.path("result");
                String transmissionId = firstNonBlank(result.path("transmissionId").asText(null), root.path("transmissionId").asText(null));
                String transmissionStatus = firstNonBlank(result.path("transmissionStatus").asText(null), root.path("transmissionStatus").asText(null));
                String documento = result.path("documento").asText(null);
                JsonNode mhRecepcion = result.path("mhRecepcion");
                String mhRecepcionJson = mhRecepcion.isMissingNode() || mhRecepcion.isNull() ? null : mhRecepcion.toString();
                invoice.applyMhWebhookSuccess(transmissionId, transmissionStatus, documento, mhRecepcionJson, now);
            } else {
                String err = firstNonBlank(root.path("message").asText(null), root.path("error").asText(null), status);
                invoice.applyMhWebhookFailure(err, now);
            }
            invoiceRepository.save(invoice);
        } catch (WebApplicationException e) {
            throw e;
        } catch (Exception e) {
            log.error("Failed to process MH webhook", e);
            throw new IllegalStateException("Invalid webhook payload", e);
        }
    }

    private static String textAt(JsonNode node, String... fieldNames) {
        if (node == null || node.isMissingNode()) {
            return null;
        }
        for (String f : fieldNames) {
            if (node.hasNonNull(f)) {
                return node.get(f).asText();
            }
        }
        return null;
    }

    private static String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String v : values) {
            if (StringUtils.isNotBlank(v)) {
                return v;
            }
        }
        return null;
    }
}
