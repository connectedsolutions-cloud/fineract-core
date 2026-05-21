package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;

public class InvoiceData {
    private Long id;
    private String status;
    private Long loanTransactionId;
    private Long loanId;
    private String loanProductName;
    private String loanExternalId;
    private Long savingsTransactionId;
    private Long clientTransactionId;
    private String numeroControl;
    private String codigoGeneracion;
    private LocalDate fecEmi;
    private String tipoDte;
    private String ambiente;
    private LocalTime horEmi;
    private String tipoMoneda;
    private String selloRecibido;
    private String mhValidationStatus;
    private String mhJobId;
    private String mhTransmissionId;
    private String mhTransmissionStatus;
    private String mhLastError;
    private String emisorNit;
    private String emisorNrc;
    private String emisorNombre;
    private String emisorCodActividad;
    private String emisorDescActividad;
    private String emisorDireccionDepartamento;
    private String emisorDireccionMunicipio;
    private String emisorDireccionComplemento;
    private String emisorTelefono;
    private String emisorCorreo;
    private String emisorCodEstableMh;
    private String emisorCodPuntoVentaMh;
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
    private List<InvoiceLineData> lines = new ArrayList<>();
    private BigDecimal totalGravada;
    private BigDecimal totalExenta;
    private BigDecimal totalNoSuj;
    private BigDecimal subTotal;
    private BigDecimal montoTotalOperacion;
    private BigDecimal totalPagar;
    private String totalLetras;

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
        data.tipoDte = invoice.getTipoDte();
        data.ambiente = invoice.getAmbiente();
        data.horEmi = invoice.getHorEmi();
        data.tipoMoneda = invoice.getTipoMoneda();
        data.selloRecibido = invoice.getSelloRecibido();
        data.mhValidationStatus = invoice.getMhValidationStatus();
        data.mhJobId = invoice.getMhJobId();
        data.mhTransmissionId = invoice.getMhTransmissionId();
        data.mhTransmissionStatus = invoice.getMhTransmissionStatus();
        data.mhLastError = invoice.getMhLastError();
        if (invoice.getIssuer() != null) {
            InvoiceIssuer issuer = invoice.getIssuer();
            data.emisorNit = issuer.getNit();
            data.emisorNrc = issuer.getNrc();
            data.emisorNombre = issuer.getNombre();
            data.emisorCodActividad = issuer.getCodActividad();
            data.emisorDescActividad = issuer.getDescActividad();
            data.emisorDireccionDepartamento = issuer.getDireccionDepartamento();
            data.emisorDireccionMunicipio = issuer.getDireccionMunicipio();
            data.emisorDireccionComplemento = issuer.getDireccionComplemento();
            data.emisorTelefono = issuer.getTelefono();
            data.emisorCorreo = issuer.getCorreo();
            data.emisorCodEstableMh = issuer.getCodEstableMh();
            data.emisorCodPuntoVentaMh = issuer.getCodPuntoVentaMh();
        }
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
        for (InvoiceLine line : invoice.getLines()) {
            data.lines.add(InvoiceLineData.from(line));
        }
        InvoiceSummary summary = invoice.getSummary();
        if (summary != null) {
            data.totalGravada = summary.getTotalGravada();
            data.totalExenta = summary.getTotalExenta();
            data.totalNoSuj = summary.getTotalNoSuj();
            data.subTotal = summary.getSubTotal();
            data.montoTotalOperacion = summary.getMontoTotalOperacion();
            data.totalPagar = summary.getTotalPagar();
            data.totalLetras = summary.getTotalLetras();
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

    public Long getLoanId() {
        return loanId;
    }

    public void setLoanId(Long loanId) {
        this.loanId = loanId;
    }

    public String getLoanProductName() {
        return loanProductName;
    }

    public void setLoanProductName(String loanProductName) {
        this.loanProductName = loanProductName;
    }

    public String getLoanExternalId() {
        return loanExternalId;
    }

    public void setLoanExternalId(String loanExternalId) {
        this.loanExternalId = loanExternalId;
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

    public String getTipoDte() {
        return tipoDte;
    }

    public String getAmbiente() {
        return ambiente;
    }

    public LocalTime getHorEmi() {
        return horEmi;
    }

    public String getTipoMoneda() {
        return tipoMoneda;
    }

    public String getSelloRecibido() {
        return selloRecibido;
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

    public String getEmisorNit() {
        return emisorNit;
    }

    public String getEmisorNrc() {
        return emisorNrc;
    }

    public String getEmisorNombre() {
        return emisorNombre;
    }

    public String getEmisorCodActividad() {
        return emisorCodActividad;
    }

    public String getEmisorDescActividad() {
        return emisorDescActividad;
    }

    public String getEmisorDireccionDepartamento() {
        return emisorDireccionDepartamento;
    }

    public String getEmisorDireccionMunicipio() {
        return emisorDireccionMunicipio;
    }

    public String getEmisorDireccionComplemento() {
        return emisorDireccionComplemento;
    }

    public String getEmisorTelefono() {
        return emisorTelefono;
    }

    public String getEmisorCorreo() {
        return emisorCorreo;
    }

    public String getEmisorCodEstableMh() {
        return emisorCodEstableMh;
    }

    public String getEmisorCodPuntoVentaMh() {
        return emisorCodPuntoVentaMh;
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

    public List<InvoiceLineData> getLines() {
        return lines;
    }

    public BigDecimal getTotalGravada() {
        return totalGravada;
    }

    public BigDecimal getTotalExenta() {
        return totalExenta;
    }

    public BigDecimal getTotalNoSuj() {
        return totalNoSuj;
    }

    public BigDecimal getSubTotal() {
        return subTotal;
    }

    public BigDecimal getMontoTotalOperacion() {
        return montoTotalOperacion;
    }

    public BigDecimal getTotalPagar() {
        return totalPagar;
    }

    public String getTotalLetras() {
        return totalLetras;
    }
}
