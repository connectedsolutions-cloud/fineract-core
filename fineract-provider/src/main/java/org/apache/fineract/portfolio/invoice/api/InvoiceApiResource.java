package org.apache.fineract.portfolio.invoice.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceData;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.invoice.service.InvoiceMhValidationService;
import org.apache.fineract.portfolio.invoice.service.InvoiceService;
import org.springframework.stereotype.Component;

@Path("/v1/invoices")
@Component
@RequiredArgsConstructor
public class InvoiceApiResource {

    private static final String RESOURCE_NAME = "INVOICE";

    private final PlatformSecurityContext context;
    private final InvoiceService invoiceService;
    private final InvoiceMhValidationService invoiceMhValidationService;

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData create(InvoiceCreateRequest request) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return InvoiceData.from(invoiceService.createDraft(request));
    }

    @GET
    @Path("{invoiceId}")
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData getById(@PathParam("invoiceId") Long invoiceId) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return invoiceService.findById(invoiceId).map(InvoiceData::from).orElse(null);
    }

    @GET
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData getByTransaction(@QueryParam("loanTransactionId") Long loanTransactionId,
            @QueryParam("savingsTransactionId") Long savingsTransactionId, @QueryParam("clientTransactionId") Long clientTransactionId) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return invoiceService.findByTransaction(loanTransactionId, savingsTransactionId, clientTransactionId).map(InvoiceData::from)
                .orElse(null);
    }

    @PUT
    @Path("{invoiceId}/metadata")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData updateMetadata(@PathParam("invoiceId") Long invoiceId, InvoiceMetadataUpdateRequest request) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return InvoiceData.from(invoiceService.updateMetadata(invoiceId, request));
    }

    @POST
    @Path("{invoiceId}/mh/validate")
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData submitMhValidationByInvoice(@PathParam("invoiceId") Long invoiceId) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return InvoiceData.from(invoiceMhValidationService.submitMhValidationByInvoiceId(invoiceId));
    }

    @POST
    @Path("mh/validate")
    @Produces({ MediaType.APPLICATION_JSON })
    public InvoiceData submitMhValidationByTransaction(@QueryParam("loanTransactionId") Long loanTransactionId,
            @QueryParam("savingsTransactionId") Long savingsTransactionId, @QueryParam("clientTransactionId") Long clientTransactionId) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        int c = (loanTransactionId != null ? 1 : 0) + (savingsTransactionId != null ? 1 : 0) + (clientTransactionId != null ? 1 : 0);
        if (c != 1) {
            throw new PlatformDataIntegrityException("error.msg.mh.validate.one.transaction",
                    "Provide exactly one of loanTransactionId, savingsTransactionId, or clientTransactionId");
        }
        if (loanTransactionId != null) {
            return InvoiceData.from(invoiceMhValidationService.submitMhValidationByLoanTransactionId(loanTransactionId));
        }
        if (savingsTransactionId != null) {
            return InvoiceData.from(invoiceMhValidationService.submitMhValidationBySavingsTransactionId(savingsTransactionId));
        }
        return InvoiceData.from(invoiceMhValidationService.submitMhValidationByClientTransactionId(clientTransactionId));
    }
}

