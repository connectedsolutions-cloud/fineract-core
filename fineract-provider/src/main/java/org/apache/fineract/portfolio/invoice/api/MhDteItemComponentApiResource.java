package org.apache.fineract.portfolio.invoice.api;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentPreviewData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentRequest;
import org.apache.fineract.portfolio.invoice.service.MhDteItemComponentService;
import org.springframework.stereotype.Component;

@Path("/v1/mh-dte-item-components")
@Component
@RequiredArgsConstructor
public class MhDteItemComponentApiResource {

    private static final String RESOURCE_NAME = "MH_DTE_ITEM_COMPONENT";

    private final PlatformSecurityContext context;
    private final MhDteItemComponentService mhDteItemComponentService;

    @GET
    @Produces({ MediaType.APPLICATION_JSON })
    public List<MhDteItemComponentData> list() {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return mhDteItemComponentService.retrieveAll();
    }

    @GET
    @Path("preview")
    @Produces({ MediaType.APPLICATION_JSON })
    public MhDteItemComponentPreviewData preview(@QueryParam("loanTransactionId") Long loanTransactionId,
            @QueryParam("clientType") String clientType, @QueryParam("includeJournalEntries") Boolean includeJournalEntries) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        if (loanTransactionId == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.mh.dte.item.component.preview.loan.txn.required",
                    "loanTransactionId is required");
        }
        boolean includeJe = Boolean.TRUE.equals(includeJournalEntries);
        return mhDteItemComponentService.preview(loanTransactionId, clientType, includeJe);
    }

    @GET
    @Path("{id}")
    @Produces({ MediaType.APPLICATION_JSON })
    public MhDteItemComponentData get(@PathParam("id") Long id) {
        context.authenticatedUser().validateHasReadPermission(RESOURCE_NAME);
        return mhDteItemComponentService.retrieveOne(id);
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public MhDteItemComponentData create(MhDteItemComponentRequest request) {
        context.authenticatedUser().validateHasCreatePermission(RESOURCE_NAME);
        return mhDteItemComponentService.create(request);
    }

    @PUT
    @Path("{id}")
    @Consumes({ MediaType.APPLICATION_JSON })
    @Produces({ MediaType.APPLICATION_JSON })
    public MhDteItemComponentData update(@PathParam("id") Long id, MhDteItemComponentRequest request) {
        context.authenticatedUser().validateHasUpdatePermission(RESOURCE_NAME);
        return mhDteItemComponentService.update(id, request);
    }

    @DELETE
    @Path("{id}")
    @Produces({ MediaType.APPLICATION_JSON })
    public void delete(@PathParam("id") Long id) {
        context.authenticatedUser().validateHasDeletePermission(RESOURCE_NAME);
        mhDteItemComponentService.delete(id);
    }
}
