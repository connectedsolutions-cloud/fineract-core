package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_invoice_issuer")
public class InvoiceIssuer extends AbstractPersistableCustom<Long> {

    @OneToOne
    @JoinColumn(name = "invoice_id", nullable = false)
    private Invoice invoice;

    @Column(name = "nit", length = 20)
    private String nit;
    @Column(name = "nrc", length = 20)
    private String nrc;
    @Column(name = "nombre", nullable = false, length = 255)
    private String nombre;
    @Column(name = "cod_actividad", length = 10)
    private String codActividad;
    @Column(name = "desc_actividad", length = 255)
    private String descActividad;
    @Column(name = "nombre_comercial", length = 255)
    private String nombreComercial;
    @Column(name = "tipo_establecimiento", length = 5)
    private String tipoEstablecimiento;
    @Column(name = "direccion_departamento", length = 10)
    private String direccionDepartamento;
    @Column(name = "direccion_municipio", length = 10)
    private String direccionMunicipio;
    @Column(name = "direccion_complemento", length = 255)
    private String direccionComplemento;
    @Column(name = "telefono", length = 30)
    private String telefono;
    @Column(name = "correo", length = 100)
    private String correo;
    @Column(name = "cod_estable_mh", length = 20)
    private String codEstableMh;
    @Column(name = "cod_estable", length = 20)
    private String codEstable;
    @Column(name = "cod_punto_venta_mh", length = 20)
    private String codPuntoVentaMh;
    @Column(name = "cod_punto_venta", length = 20)
    private String codPuntoVenta;

    protected InvoiceIssuer() {}

    public static InvoiceIssuer empty() {
        return new InvoiceIssuer();
    }

    public void setInvoice(Invoice invoice) {
        this.invoice = invoice;
    }

    public String getNombre() {
        return nombre;
    }

    public void setNombre(String nombre) {
        this.nombre = nombre;
    }

    public String getNit() {
        return nit;
    }

    public String getNrc() {
        return nrc;
    }

    public String getCodActividad() {
        return codActividad;
    }

    public String getDescActividad() {
        return descActividad;
    }

    public String getNombreComercial() {
        return nombreComercial;
    }

    public String getTipoEstablecimiento() {
        return tipoEstablecimiento;
    }

    public String getDireccionDepartamento() {
        return direccionDepartamento;
    }

    public String getDireccionMunicipio() {
        return direccionMunicipio;
    }

    public String getDireccionComplemento() {
        return direccionComplemento;
    }

    public String getTelefono() {
        return telefono;
    }

    public String getCorreo() {
        return correo;
    }

    public String getCodEstableMh() {
        return codEstableMh;
    }

    public String getCodEstable() {
        return codEstable;
    }

    public String getCodPuntoVentaMh() {
        return codPuntoVentaMh;
    }

    public String getCodPuntoVenta() {
        return codPuntoVenta;
    }
}

