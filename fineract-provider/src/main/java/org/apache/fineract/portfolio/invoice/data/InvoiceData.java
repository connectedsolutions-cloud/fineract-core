package org.apache.fineract.portfolio.invoice.data;

import java.time.LocalDate;
import org.apache.fineract.portfolio.invoice.domain.Invoice;

public class InvoiceData {
    private Long id;
    private String status;
    private Long loanTransactionId;
    private Long savingsTransactionId;
    private Long clientTransactionId;
    private String numeroControl;
    private String codigoGeneracion;
    private LocalDate fecEmi;
    private String mhValidationStatus;
    private String mhJobId;
    private String mhTransmissionId;
    private String mhTransmissionStatus;

    public static InvoiceData from(Invoice invoice) {
        InvoiceData data = new InvoiceData();
        data.id = invoice.getId();
        data.status = invoice.getStatus().name();
        data.loanTransactionId = invoice.getLoanTransactionId();
        data.savingsTransactionId = invoice.getSavingsTransactionId();
        data.clientTransactionId = invoice.getClientTransactionId();
        data.numeroControl = invoice.getNumeroControl();
        data.codigoGeneracion = invoice.getCodigoGeneracion();
        data.fecEmi = invoice.getFecEmi();
        data.mhValidationStatus = invoice.getMhValidationStatus();
        data.mhJobId = invoice.getMhJobId();
        data.mhTransmissionId = invoice.getMhTransmissionId();
        data.mhTransmissionStatus = invoice.getMhTransmissionStatus();
        return data;
    }

    public Long getId() {
        return id;
    }

    public String getStatus() {
        return status;
    }

    public Long getLoanTransactionId() {
        return loanTransactionId;
    }

    public Long getSavingsTransactionId() {
        return savingsTransactionId;
    }

    public Long getClientTransactionId() {
        return clientTransactionId;
    }

    public String getNumeroControl() {
        return numeroControl;
    }

    public String getCodigoGeneracion() {
        return codigoGeneracion;
    }

    public LocalDate getFecEmi() {
        return fecEmi;
    }

    public String getMhValidationStatus() {
        return mhValidationStatus;
    }

    public String getMhJobId() {
        return mhJobId;
    }

    public String getMhTransmissionId() {
        return mhTransmissionId;
    }

    public String getMhTransmissionStatus() {
        return mhTransmissionStatus;
    }
}

