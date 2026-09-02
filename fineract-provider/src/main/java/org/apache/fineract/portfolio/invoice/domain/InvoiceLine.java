package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.infrastructure.core.persistence.converter.JsonbStringAttributeConverter;

@Entity
@Table(name = "m_invoice_line")
public class InvoiceLine extends AbstractPersistableCustom<Long> {

    @ManyToOne
    @JoinColumn(name = "invoice_id", nullable = false)
    private Invoice invoice;

    @Column(name = "num_item", nullable = false)
    private Integer numItem;

    @Column(name = "tipo_item", nullable = false)
    private Integer tipoItem;

    @Column(name = "cantidad", precision = 19, scale = 6, nullable = false)
    private BigDecimal cantidad;

    @Column(name = "uni_medida")
    private Integer uniMedida;

    @Column(name = "descripcion", nullable = false, length = 500)
    private String descripcion;

    @Column(name = "precio_uni", precision = 19, scale = 6, nullable = false)
    private BigDecimal precioUni;

    @Column(name = "monto_descu", precision = 19, scale = 6)
    private BigDecimal montoDescu;

    @Column(name = "venta_no_suj", precision = 19, scale = 6)
    private BigDecimal ventaNoSuj;

    @Column(name = "venta_exenta", precision = 19, scale = 6)
    private BigDecimal ventaExenta;

    @Column(name = "venta_gravada", precision = 19, scale = 6)
    private BigDecimal ventaGravada;

    @Column(name = "tributos_json", columnDefinition = "json")
    @Convert(converter = JsonbStringAttributeConverter.class)
    private String tributosJson;

    @Column(name = "no_gravado", precision = 19, scale = 6)
    private BigDecimal noGravado;

    protected InvoiceLine() {}

    public static InvoiceLine of(Integer numItem, Integer tipoItem, BigDecimal cantidad, Integer uniMedida, String descripcion,
            BigDecimal precioUni, BigDecimal montoDescu, BigDecimal ventaNoSuj, BigDecimal ventaExenta, BigDecimal ventaGravada,
            String tributosJson, BigDecimal noGravado) {
        InvoiceLine line = new InvoiceLine();
        line.numItem = numItem;
        line.tipoItem = tipoItem;
        line.cantidad = cantidad;
        line.uniMedida = uniMedida;
        line.descripcion = descripcion;
        line.precioUni = precioUni;
        line.montoDescu = montoDescu;
        line.ventaNoSuj = ventaNoSuj;
        line.ventaExenta = ventaExenta;
        line.ventaGravada = ventaGravada;
        line.tributosJson = tributosJson;
        line.noGravado = noGravado;
        return line;
    }

    public void setInvoice(Invoice invoice) {
        this.invoice = invoice;
    }

    public Integer getNumItem() {
        return numItem;
    }

    public Integer getTipoItem() {
        return tipoItem;
    }

    public BigDecimal getCantidad() {
        return cantidad;
    }

    public Integer getUniMedida() {
        return uniMedida;
    }

    public String getDescripcion() {
        return descripcion;
    }

    public String getTributosJson() {
        return tributosJson;
    }

    public BigDecimal getNoGravado() {
        return noGravado;
    }

    public BigDecimal getVentaNoSuj() {
        return ventaNoSuj == null ? BigDecimal.ZERO : ventaNoSuj;
    }

    public BigDecimal getVentaExenta() {
        return ventaExenta == null ? BigDecimal.ZERO : ventaExenta;
    }

    public BigDecimal getVentaGravada() {
        return ventaGravada == null ? BigDecimal.ZERO : ventaGravada;
    }

    public BigDecimal getMontoDescu() {
        return montoDescu == null ? BigDecimal.ZERO : montoDescu;
    }

    public BigDecimal getPrecioUni() {
        return precioUni == null ? BigDecimal.ZERO : precioUni;
    }
}
