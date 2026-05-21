package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;

public class InvoiceLineData {

    private Integer numItem;
    private String descripcion;
    private BigDecimal cantidad;
    private BigDecimal precioUni;
    private BigDecimal ventaGravada;
    private BigDecimal ventaExenta;
    private BigDecimal ventaNoSuj;
    private BigDecimal noGravado;

    public static InvoiceLineData from(InvoiceLine line) {
        InvoiceLineData data = new InvoiceLineData();
        data.numItem = line.getNumItem();
        data.descripcion = line.getDescripcion();
        data.cantidad = line.getCantidad();
        data.precioUni = line.getPrecioUni();
        data.ventaGravada = line.getVentaGravada();
        data.ventaExenta = line.getVentaExenta();
        data.ventaNoSuj = line.getVentaNoSuj();
        data.noGravado = line.getNoGravado();
        return data;
    }

    public Integer getNumItem() {
        return numItem;
    }

    public String getDescripcion() {
        return descripcion;
    }

    public BigDecimal getCantidad() {
        return cantidad;
    }

    public BigDecimal getPrecioUni() {
        return precioUni;
    }

    public BigDecimal getVentaGravada() {
        return ventaGravada;
    }

    public BigDecimal getVentaExenta() {
        return ventaExenta;
    }

    public BigDecimal getVentaNoSuj() {
        return ventaNoSuj;
    }

    public BigDecimal getNoGravado() {
        return noGravado;
    }
}
