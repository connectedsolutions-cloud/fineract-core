package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import lombok.Getter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.persistence.converter.JsonbStringAttributeConverter;

@Entity
@Table(name = "m_invoice_summary")
@Getter
public class InvoiceSummary extends AbstractPersistableCustom<Long> {

    @OneToOne
    @JoinColumn(name = "invoice_id", nullable = false)
    private Invoice invoice;

    @Column(name = "total_no_suj", precision = 19, scale = 6)
    private BigDecimal totalNoSuj;
    @Column(name = "total_exenta", precision = 19, scale = 6)
    private BigDecimal totalExenta;
    @Column(name = "total_gravada", precision = 19, scale = 6)
    private BigDecimal totalGravada;
    @Column(name = "sub_total_ventas", precision = 19, scale = 6)
    private BigDecimal subTotalVentas;
    @Column(name = "descu_no_suj", precision = 19, scale = 6)
    private BigDecimal descuNoSuj;
    @Column(name = "descu_exenta", precision = 19, scale = 6)
    private BigDecimal descuExenta;
    @Column(name = "descu_gravada", precision = 19, scale = 6)
    private BigDecimal descuGravada;
    @Column(name = "tributos_json", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String tributosJson;
    @Column(name = "sub_total", precision = 19, scale = 6)
    private BigDecimal subTotal;
    @Column(name = "iva_percibido", precision = 19, scale = 6)
    private BigDecimal ivaPercibido;
    @Column(name = "iva_retenido", precision = 19, scale = 6)
    private BigDecimal ivaRetenido;
    @Column(name = "rete_renta", precision = 19, scale = 6)
    private BigDecimal reteRenta;
    @Column(name = "monto_total_operacion", precision = 19, scale = 6)
    private BigDecimal montoTotalOperacion;
    @Column(name = "total_pagar", precision = 19, scale = 6)
    private BigDecimal totalPagar;
    @Column(name = "total_letras", length = 500)
    private String totalLetras;
    @Column(name = "condicion_operacion")
    private Integer condicionOperacion;
    @Column(name = "pagos_json", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String pagosJson;

    protected InvoiceSummary() {}

    public static InvoiceSummary basic(BigDecimal totalNoSuj, BigDecimal totalExenta, BigDecimal totalGravada, BigDecimal subTotalVentas,
            BigDecimal descuNoSuj, BigDecimal descuExenta, BigDecimal descuGravada, BigDecimal subTotal, BigDecimal montoTotalOperacion,
            BigDecimal totalPagar) {
        InvoiceSummary summary = new InvoiceSummary();
        summary.totalNoSuj = totalNoSuj;
        summary.totalExenta = totalExenta;
        summary.totalGravada = totalGravada;
        summary.subTotalVentas = subTotalVentas;
        summary.descuNoSuj = descuNoSuj;
        summary.descuExenta = descuExenta;
        summary.descuGravada = descuGravada;
        summary.subTotal = subTotal;
        summary.montoTotalOperacion = montoTotalOperacion;
        summary.totalPagar = totalPagar;
        return summary;
    }

    public void setInvoice(Invoice invoice) {
        this.invoice = invoice;
    }
}
