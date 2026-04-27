package org.apache.fineract.portfolio.invoice.data;

public class InvoiceMetadataUpdateRequest {
    private String firmaElectronica;
    private String selloRecibido;
    private String authorityStatus;
    private String authorityMessage;
    private String nextStatus;

    public String getFirmaElectronica() {
        return firmaElectronica;
    }

    public void setFirmaElectronica(String firmaElectronica) {
        this.firmaElectronica = firmaElectronica;
    }

    public String getSelloRecibido() {
        return selloRecibido;
    }

    public void setSelloRecibido(String selloRecibido) {
        this.selloRecibido = selloRecibido;
    }

    public String getAuthorityStatus() {
        return authorityStatus;
    }

    public void setAuthorityStatus(String authorityStatus) {
        this.authorityStatus = authorityStatus;
    }

    public String getAuthorityMessage() {
        return authorityMessage;
    }

    public void setAuthorityMessage(String authorityMessage) {
        this.authorityMessage = authorityMessage;
    }

    public String getNextStatus() {
        return nextStatus;
    }

    public void setNextStatus(String nextStatus) {
        this.nextStatus = nextStatus;
    }
}

