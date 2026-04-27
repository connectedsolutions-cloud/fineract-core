package org.apache.fineract.portfolio.invoice.data;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;

public class InvoiceCreateRequest {
    private Long loanTransactionId;
    private Long savingsTransactionId;
    private Long clientTransactionId;
    private Integer version;
    private String ambiente;
    private String tipoDte;
    private String numeroControl;
    private String codigoGeneracion;
    private Integer tipoModelo;
    private Integer tipoOperacion;
    private LocalDate fecEmi;
    private LocalTime horEmi;
    private String tipoMoneda;
    private Integer tipoContingencia;
    private String motivoContin;
    private String emisorNombre;
    private String receptorNombre;
    private List<InvoiceLineRequest> lines;

    public Long getLoanTransactionId() {
        return loanTransactionId;
    }

    public void setLoanTransactionId(Long loanTransactionId) {
        this.loanTransactionId = loanTransactionId;
    }

    public Long getSavingsTransactionId() {
        return savingsTransactionId;
    }

    public void setSavingsTransactionId(Long savingsTransactionId) {
        this.savingsTransactionId = savingsTransactionId;
    }

    public Long getClientTransactionId() {
        return clientTransactionId;
    }

    public void setClientTransactionId(Long clientTransactionId) {
        this.clientTransactionId = clientTransactionId;
    }

    public Integer getVersion() {
        return version;
    }

    public void setVersion(Integer version) {
        this.version = version;
    }

    public String getAmbiente() {
        return ambiente;
    }

    public void setAmbiente(String ambiente) {
        this.ambiente = ambiente;
    }

    public String getTipoDte() {
        return tipoDte;
    }

    public void setTipoDte(String tipoDte) {
        this.tipoDte = tipoDte;
    }

    public String getNumeroControl() {
        return numeroControl;
    }

    public void setNumeroControl(String numeroControl) {
        this.numeroControl = numeroControl;
    }

    public String getCodigoGeneracion() {
        return codigoGeneracion;
    }

    public void setCodigoGeneracion(String codigoGeneracion) {
        this.codigoGeneracion = codigoGeneracion;
    }

    public Integer getTipoModelo() {
        return tipoModelo;
    }

    public void setTipoModelo(Integer tipoModelo) {
        this.tipoModelo = tipoModelo;
    }

    public Integer getTipoOperacion() {
        return tipoOperacion;
    }

    public void setTipoOperacion(Integer tipoOperacion) {
        this.tipoOperacion = tipoOperacion;
    }

    public LocalDate getFecEmi() {
        return fecEmi;
    }

    public void setFecEmi(LocalDate fecEmi) {
        this.fecEmi = fecEmi;
    }

    public LocalTime getHorEmi() {
        return horEmi;
    }

    public void setHorEmi(LocalTime horEmi) {
        this.horEmi = horEmi;
    }

    public String getTipoMoneda() {
        return tipoMoneda;
    }

    public void setTipoMoneda(String tipoMoneda) {
        this.tipoMoneda = tipoMoneda;
    }

    public Integer getTipoContingencia() {
        return tipoContingencia;
    }

    public void setTipoContingencia(Integer tipoContingencia) {
        this.tipoContingencia = tipoContingencia;
    }

    public String getMotivoContin() {
        return motivoContin;
    }

    public void setMotivoContin(String motivoContin) {
        this.motivoContin = motivoContin;
    }

    public String getEmisorNombre() {
        return emisorNombre;
    }

    public void setEmisorNombre(String emisorNombre) {
        this.emisorNombre = emisorNombre;
    }

    public String getReceptorNombre() {
        return receptorNombre;
    }

    public void setReceptorNombre(String receptorNombre) {
        this.receptorNombre = receptorNombre;
    }

    public List<InvoiceLineRequest> getLines() {
        return lines;
    }

    public void setLines(List<InvoiceLineRequest> lines) {
        this.lines = lines;
    }
}

