package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;

public class InvoiceLineRequest {
    private Integer numItem;
    private Integer tipoItem;
    private BigDecimal cantidad;
    private Integer uniMedida;
    private String descripcion;
    private BigDecimal precioUni;
    private BigDecimal montoDescu;
    private BigDecimal ventaNoSuj;
    private BigDecimal ventaExenta;
    private BigDecimal ventaGravada;
    private String tributos;
    private BigDecimal noGravado;

    public Integer getNumItem() {
        return numItem;
    }

    public void setNumItem(Integer numItem) {
        this.numItem = numItem;
    }

    public Integer getTipoItem() {
        return tipoItem;
    }

    public void setTipoItem(Integer tipoItem) {
        this.tipoItem = tipoItem;
    }

    public BigDecimal getCantidad() {
        return cantidad;
    }

    public void setCantidad(BigDecimal cantidad) {
        this.cantidad = cantidad;
    }

    public Integer getUniMedida() {
        return uniMedida;
    }

    public void setUniMedida(Integer uniMedida) {
        this.uniMedida = uniMedida;
    }

    public String getDescripcion() {
        return descripcion;
    }

    public void setDescripcion(String descripcion) {
        this.descripcion = descripcion;
    }

    public BigDecimal getPrecioUni() {
        return precioUni;
    }

    public void setPrecioUni(BigDecimal precioUni) {
        this.precioUni = precioUni;
    }

    public BigDecimal getMontoDescu() {
        return montoDescu;
    }

    public void setMontoDescu(BigDecimal montoDescu) {
        this.montoDescu = montoDescu;
    }

    public BigDecimal getVentaNoSuj() {
        return ventaNoSuj;
    }

    public void setVentaNoSuj(BigDecimal ventaNoSuj) {
        this.ventaNoSuj = ventaNoSuj;
    }

    public BigDecimal getVentaExenta() {
        return ventaExenta;
    }

    public void setVentaExenta(BigDecimal ventaExenta) {
        this.ventaExenta = ventaExenta;
    }

    public BigDecimal getVentaGravada() {
        return ventaGravada;
    }

    public void setVentaGravada(BigDecimal ventaGravada) {
        this.ventaGravada = ventaGravada;
    }

    public String getTributos() {
        return tributos;
    }

    public void setTributos(String tributos) {
        this.tributos = tributos;
    }

    public BigDecimal getNoGravado() {
        return noGravado;
    }

    public void setNoGravado(BigDecimal noGravado) {
        this.noGravado = noGravado;
    }
}

