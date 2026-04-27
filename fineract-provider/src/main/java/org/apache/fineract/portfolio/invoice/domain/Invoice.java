package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.OneToMany;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.AbstractAuditableCustom;

@Entity
@Table(name = "m_invoice")
public class Invoice extends AbstractAuditableCustom {

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 40)
    private InvoiceStatus status;

    @Column(name = "loan_transaction_id")
    private Long loanTransactionId;

    @Column(name = "savings_transaction_id")
    private Long savingsTransactionId;

    @Column(name = "client_transaction_id")
    private Long clientTransactionId;

    @Column(name = "version", nullable = false)
    private Integer version;

    @Column(name = "ambiente", nullable = false, length = 2)
    private String ambiente;

    @Column(name = "tipo_dte", nullable = false, length = 4)
    private String tipoDte;

    @Column(name = "numero_control", nullable = false, length = 31)
    private String numeroControl;

    @Column(name = "codigo_generacion", nullable = false, length = 36)
    private String codigoGeneracion;

    @Column(name = "tipo_modelo", nullable = false)
    private Integer tipoModelo;

    @Column(name = "tipo_operacion", nullable = false)
    private Integer tipoOperacion;

    @Column(name = "fec_emi", nullable = false)
    private LocalDate fecEmi;

    @Column(name = "hor_emi", nullable = false)
    private LocalTime horEmi;

    @Column(name = "tipo_moneda", nullable = false, length = 3)
    private String tipoMoneda;

    @Column(name = "tipo_contingencia")
    private Integer tipoContingencia;

    @Column(name = "motivo_contin", length = 255)
    private String motivoContin;

    @Column(name = "firma_electronica", columnDefinition = "text")
    private String firmaElectronica;

    @Column(name = "sello_recibido", length = 40)
    private String selloRecibido;

    @Column(name = "authority_status", length = 40)
    private String authorityStatus;

    @Column(name = "authority_message", columnDefinition = "text")
    private String authorityMessage;

    @Column(name = "authority_processed_at")
    private LocalDateTime authorityProcessedAt;

    @Column(name = "mh_job_id", length = 100)
    private String mhJobId;

    @Column(name = "mh_transmission_id", length = 100)
    private String mhTransmissionId;

    @Column(name = "mh_transmission_status", length = 80)
    private String mhTransmissionStatus;

    @Column(name = "mh_documento_jws", columnDefinition = "text")
    private String mhDocumentoJws;

    @Column(name = "mh_recepcion_json", columnDefinition = "text")
    private String mhRecepcionJson;

    @Column(name = "mh_last_error", columnDefinition = "text")
    private String mhLastError;

    @Column(name = "mh_validation_status", length = 40)
    private String mhValidationStatus;

    @Column(name = "mh_submitted_at")
    private LocalDateTime mhSubmittedAt;

    @Column(name = "mh_processed_at")
    private LocalDateTime mhProcessedAt;

    @Column(name = "mh_callback_received_at")
    private LocalDateTime mhCallbackReceivedAt;

    @OneToMany(mappedBy = "invoice", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<InvoiceLine> lines = new ArrayList<>();

    @OneToMany(mappedBy = "invoice", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<InvoiceRelatedDocument> relatedDocuments = new ArrayList<>();

    @OneToOne(mappedBy = "invoice", cascade = CascadeType.ALL, orphanRemoval = true)
    private InvoiceIssuer issuer;

    @OneToOne(mappedBy = "invoice", cascade = CascadeType.ALL, orphanRemoval = true)
    private InvoiceReceiver receiver;

    @OneToOne(mappedBy = "invoice", cascade = CascadeType.ALL, orphanRemoval = true)
    private InvoiceSummary summary;

    protected Invoice() {}

    public static Invoice draft(Long loanTransactionId, Long savingsTransactionId, Long clientTransactionId, Integer version, String ambiente,
            String tipoDte, String numeroControl, String codigoGeneracion, Integer tipoModelo, Integer tipoOperacion, LocalDate fecEmi,
            LocalTime horEmi, String tipoMoneda) {
        Invoice invoice = new Invoice();
        invoice.status = InvoiceStatus.DRAFT;
        invoice.loanTransactionId = loanTransactionId;
        invoice.savingsTransactionId = savingsTransactionId;
        invoice.clientTransactionId = clientTransactionId;
        invoice.version = version;
        invoice.ambiente = ambiente;
        invoice.tipoDte = tipoDte;
        invoice.numeroControl = numeroControl;
        invoice.codigoGeneracion = codigoGeneracion;
        invoice.tipoModelo = tipoModelo;
        invoice.tipoOperacion = tipoOperacion;
        invoice.fecEmi = fecEmi;
        invoice.horEmi = horEmi;
        invoice.tipoMoneda = tipoMoneda;
        return invoice;
    }

    public void setStatus(InvoiceStatus status) {
        this.status = status;
    }

    public InvoiceStatus getStatus() {
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

    public String getCodigoGeneracion() {
        return codigoGeneracion;
    }

    public String getNumeroControl() {
        return numeroControl;
    }

    public Integer getVersion() {
        return version;
    }

    public String getAmbiente() {
        return ambiente;
    }

    public String getTipoDte() {
        return tipoDte;
    }

    public Integer getTipoModelo() {
        return tipoModelo;
    }

    public Integer getTipoOperacion() {
        return tipoOperacion;
    }

    public LocalTime getHorEmi() {
        return horEmi;
    }

    public String getTipoMoneda() {
        return tipoMoneda;
    }

    public Integer getTipoContingencia() {
        return tipoContingencia;
    }

    public String getMotivoContin() {
        return motivoContin;
    }

    public String getAuthorityStatus() {
        return authorityStatus;
    }

    public String getAuthorityMessage() {
        return authorityMessage;
    }

    public LocalDateTime getAuthorityProcessedAt() {
        return authorityProcessedAt;
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

    public String getMhDocumentoJws() {
        return mhDocumentoJws;
    }

    public String getMhRecepcionJson() {
        return mhRecepcionJson;
    }

    public String getMhLastError() {
        return mhLastError;
    }

    public String getMhValidationStatus() {
        return mhValidationStatus;
    }

    public LocalDateTime getMhSubmittedAt() {
        return mhSubmittedAt;
    }

    public LocalDateTime getMhProcessedAt() {
        return mhProcessedAt;
    }

    public LocalDateTime getMhCallbackReceivedAt() {
        return mhCallbackReceivedAt;
    }

    public void markMhSubmitPending(String jobId, LocalDateTime submittedAt) {
        this.mhJobId = jobId;
        this.mhSubmittedAt = submittedAt;
        this.mhValidationStatus = "PENDING";
        this.mhLastError = null;
    }

    public void applyMhWebhookSuccess(String transmissionId, String transmissionStatus, String documentoJws, String mhRecepcionJson,
            LocalDateTime processedAt) {
        this.mhTransmissionId = transmissionId;
        this.mhTransmissionStatus = transmissionStatus;
        this.mhDocumentoJws = documentoJws;
        this.mhRecepcionJson = mhRecepcionJson;
        this.mhProcessedAt = processedAt;
        this.mhCallbackReceivedAt = processedAt;
        this.mhValidationStatus = "SUCCESS";
        this.mhLastError = null;
        if ("PROCESADO".equalsIgnoreCase(transmissionStatus)) {
            this.status = InvoiceStatus.ACCEPTED;
        }
    }

    public void applyMhWebhookFailure(String message, LocalDateTime processedAt) {
        this.mhLastError = message;
        this.mhProcessedAt = processedAt;
        this.mhCallbackReceivedAt = processedAt;
        this.mhValidationStatus = "FAILED";
        this.status = InvoiceStatus.REJECTED;
    }

    public LocalDate getFecEmi() {
        return fecEmi;
    }

    public void setContingency(Integer tipoContingencia, String motivoContin) {
        this.tipoContingencia = tipoContingencia;
        this.motivoContin = motivoContin;
    }

    public void setAuthorityData(String authorityStatus, String authorityMessage, String selloRecibido, LocalDateTime authorityProcessedAt) {
        this.authorityStatus = authorityStatus;
        this.authorityMessage = authorityMessage;
        this.selloRecibido = selloRecibido;
        this.authorityProcessedAt = authorityProcessedAt;
    }

    public void setFirmaElectronica(String firmaElectronica) {
        this.firmaElectronica = firmaElectronica;
    }

    public String getFirmaElectronica() {
        return firmaElectronica;
    }

    public String getSelloRecibido() {
        return selloRecibido;
    }

    public List<InvoiceLine> getLines() {
        return lines;
    }

    public List<InvoiceRelatedDocument> getRelatedDocuments() {
        return relatedDocuments;
    }

    public void replaceLines(List<InvoiceLine> newLines) {
        this.lines.clear();
        for (InvoiceLine line : newLines) {
            line.setInvoice(this);
            this.lines.add(line);
        }
    }

    public void setIssuer(InvoiceIssuer issuer) {
        issuer.setInvoice(this);
        this.issuer = issuer;
    }

    public InvoiceIssuer getIssuer() {
        return issuer;
    }

    public void setReceiver(InvoiceReceiver receiver) {
        receiver.setInvoice(this);
        this.receiver = receiver;
    }

    public InvoiceReceiver getReceiver() {
        return receiver;
    }

    public void setSummary(InvoiceSummary summary) {
        summary.setInvoice(this);
        this.summary = summary;
    }

    public InvoiceSummary getSummary() {
        return summary;
    }
}

