package org.apache.fineract.portfolio.invoice.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.HttpHeaders;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.invoice.service.InvoiceMhWebhookService;
import org.springframework.stereotype.Component;

@Path("/v1/webhooks/mh")
@Component
@RequiredArgsConstructor
public class MhWebhookApiResource {

    private static final String HEADER_WEBHOOK_SECRET = "X-Webhook-Secret";

    private final InvoiceMhWebhookService invoiceMhWebhookService;

    @POST
    @Path("validation-result")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response receive(String body, @Context HttpHeaders headers) {
        invoiceMhWebhookService.validateHeaderSecret(headers.getHeaderString(HEADER_WEBHOOK_SECRET));
        invoiceMhWebhookService.handlePayload(body);
        return Response.noContent().build();
    }
}
