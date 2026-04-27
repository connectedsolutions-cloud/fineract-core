package org.apache.fineract.portfolio.invoice.mh;

public record MhFirmaCredentials(String nitFourteenDigits, String passwordPri, String signingApiKey, String firmaSecret) {

    public boolean hasOutboundAuth() {
        return signingApiKey != null && !signingApiKey.isBlank() || firmaSecret != null && !firmaSecret.isBlank();
    }
}
