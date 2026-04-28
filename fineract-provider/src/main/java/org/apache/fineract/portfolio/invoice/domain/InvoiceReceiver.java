package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_invoice_receiver")
public class InvoiceReceiver extends AbstractPersistableCustom<Long> {

    @OneToOne
    @JoinColumn(name = "invoice_id", nullable = false)
    private Invoice invoice;

    @Column(name = "nit", length = 20)
    private String nit;
    @Column(name = "doc_id", length = 30)
    private String docId;
    @Column(name = "tipo_documento", length = 2)
    private String tipoDocumento;
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

    protected InvoiceReceiver() {}

    public static InvoiceReceiver empty() {
        return new InvoiceReceiver();
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

    public String getDocId() {
        return docId;
    }

    public void setDocId(String docId) {
        this.docId = docId;
    }

    public String getNrc() {
        return nrc;
    }

    public void setNrc(String nrc) {
        this.nrc = nrc;
    }

    public String getTipoDocumento() {
        return tipoDocumento;
    }

    public void setTipoDocumento(String tipoDocumento) {
        this.tipoDocumento = tipoDocumento;
    }

    public String getCodActividad() {
        return codActividad;
    }

    public void setCodActividad(String codActividad) {
        this.codActividad = codActividad;
    }

    public String getDescActividad() {
        return descActividad;
    }

    public void setDescActividad(String descActividad) {
        this.descActividad = descActividad;
    }

    public String getNombreComercial() {
        return nombreComercial;
    }

    public void setNombreComercial(String nombreComercial) {
        this.nombreComercial = nombreComercial;
    }

    public String getDireccionDepartamento() {
        return direccionDepartamento;
    }

    public void setDireccionDepartamento(String direccionDepartamento) {
        this.direccionDepartamento = direccionDepartamento;
    }

    public String getDireccionMunicipio() {
        return direccionMunicipio;
    }

    public void setDireccionMunicipio(String direccionMunicipio) {
        this.direccionMunicipio = direccionMunicipio;
    }

    public String getDireccionComplemento() {
        return direccionComplemento;
    }

    public void setDireccionComplemento(String direccionComplemento) {
        this.direccionComplemento = direccionComplemento;
    }

    public String getTelefono() {
        return telefono;
    }

    public void setTelefono(String telefono) {
        this.telefono = telefono;
    }

    public String getCorreo() {
        return correo;
    }

    public void setCorreo(String correo) {
        this.correo = correo;
    }

    public void setNit(String nit) {
        this.nit = nit;
    }
}

