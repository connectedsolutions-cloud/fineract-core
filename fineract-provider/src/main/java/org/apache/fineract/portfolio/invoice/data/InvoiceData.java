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
    private String mhLastError;
    private String receptorTipoDocumento;
    private String receptorNombre;
    private String receptorDocId;
    private String receptorNit;
    private String receptorNrc;
    private String receptorCodActividad;
    private String receptorDescActividad;
    private String receptorNombreComercial;
    private String receptorDireccionDepartamento;
    private String receptorDireccionMunicipio;
    private String receptorDireccionComplemento;
    private String receptorCorreo;
    private String receptorTelefono;

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
        data.mhLastError = invoice.getMhLastError();
        if (invoice.getReceiver() != null) {
            data.receptorTipoDocumento = invoice.getReceiver().getTipoDocumento();
            data.receptorNombre = invoice.getReceiver().getNombre();
            data.receptorDocId = invoice.getReceiver().getDocId();
            data.receptorNit = invoice.getReceiver().getNit();
            data.receptorNrc = invoice.getReceiver().getNrc();
            data.receptorCodActividad = invoice.getReceiver().getCodActividad();
            data.receptorDescActividad = invoice.getReceiver().getDescActividad();
            data.receptorNombreComercial = invoice.getReceiver().getNombreComercial();
            data.receptorDireccionDepartamento = invoice.getReceiver().getDireccionDepartamento();
            data.receptorDireccionMunicipio = invoice.getReceiver().getDireccionMunicipio();
            data.receptorDireccionComplemento = invoice.getReceiver().getDireccionComplemento();
            data.receptorCorreo = invoice.getReceiver().getCorreo();
            data.receptorTelefono = invoice.getReceiver().getTelefono();
        }
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

    public String getMhLastError() {
        return mhLastError;
    }

    public String getReceptorTipoDocumento() {
        return receptorTipoDocumento;
    }

    public String getReceptorNombre() {
        return receptorNombre;
    }

    public String getReceptorDocId() {
        return receptorDocId;
    }

    public String getReceptorNit() {
        return receptorNit;
    }

    public String getReceptorNrc() {
        return receptorNrc;
    }

    public String getReceptorCodActividad() {
        return receptorCodActividad;
    }

    public String getReceptorDescActividad() {
        return receptorDescActividad;
    }

    public String getReceptorNombreComercial() {
        return receptorNombreComercial;
    }

    public String getReceptorDireccionDepartamento() {
        return receptorDireccionDepartamento;
    }

    public String getReceptorDireccionMunicipio() {
        return receptorDireccionMunicipio;
    }

    public String getReceptorDireccionComplemento() {
        return receptorDireccionComplemento;
    }

    public String getReceptorCorreo() {
        return receptorCorreo;
    }

    public String getReceptorTelefono() {
        return receptorTelefono;
    }
}

