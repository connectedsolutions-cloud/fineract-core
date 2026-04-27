package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.LocalDate;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_invoice_related_document")
public class InvoiceRelatedDocument extends AbstractPersistableCustom<Long> {

    @ManyToOne
    @JoinColumn(name = "invoice_id", nullable = false)
    private Invoice invoice;

    @Column(name = "tipo_documento", length = 5)
    private String tipoDocumento;
    @Column(name = "tipo_generacion", length = 1)
    private String tipoGeneracion;
    @Column(name = "numero_documento", length = 64)
    private String numeroDocumento;
    @Column(name = "fecha_generacion")
    private LocalDate fechaGeneracion;

    protected InvoiceRelatedDocument() {}

    public static InvoiceRelatedDocument of(String tipoDocumento, String tipoGeneracion, String numeroDocumento,
            LocalDate fechaGeneracion) {
        InvoiceRelatedDocument doc = new InvoiceRelatedDocument();
        doc.tipoDocumento = tipoDocumento;
        doc.tipoGeneracion = tipoGeneracion;
        doc.numeroDocumento = numeroDocumento;
        doc.fechaGeneracion = fechaGeneracion;
        return doc;
    }

    public void setInvoice(Invoice invoice) {
        this.invoice = invoice;
    }

    public String getTipoDocumento() {
        return tipoDocumento;
    }

    public String getTipoGeneracion() {
        return tipoGeneracion;
    }

    public String getNumeroDocumento() {
        return numeroDocumento;
    }

    public LocalDate getFechaGeneracion() {
        return fechaGeneracion;
    }
}

