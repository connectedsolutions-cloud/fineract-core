package org.apache.fineract.portfolio.invoice.mh;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRelatedDocument;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.springframework.stereotype.Component;

@Component
public class DteJsonBuilder {

    private final ObjectMapper objectMapper;

    public DteJsonBuilder() {
        this.objectMapper = new ObjectMapper();
        this.objectMapper.registerModule(new JavaTimeModule());
        this.objectMapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }

    public Map<String, Object> buildDteJsonObject(Invoice invoice) {
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("identificacion", buildIdentificacion(invoice));
        root.put("documentoRelacionado", buildDocumentoRelacionado(invoice));
        if (invoice.getIssuer() != null) {
            root.put("emisor", buildEmisor(invoice.getIssuer()));
        }
        if (invoice.getReceiver() != null) {
            root.put("receptor", buildReceptor(invoice.getReceiver()));
        }
        root.put("cuerpoDocumento", buildCuerpo(invoice));
        if (invoice.getSummary() != null) {
            root.put("resumen", buildResumen(invoice.getSummary()));
        }
        if (invoice.getFirmaElectronica() != null) {
            root.put("firmaElectronica", invoice.getFirmaElectronica());
        }
        return root;
    }

    public String buildDteJsonString(Invoice invoice) {
        try {
            return objectMapper.writeValueAsString(buildDteJsonObject(invoice));
        } catch (Exception e) {
            throw new IllegalStateException("Failed to serialize DTE JSON", e);
        }
    }

    public String toJsonString(Map<String, Object> payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to serialize DTE JSON payload", e);
        }
    }

    private Map<String, Object> buildIdentificacion(Invoice invoice) {
        Map<String, Object> id = new LinkedHashMap<>();
        id.put("version", invoice.getVersion());
        id.put("ambiente", invoice.getAmbiente());
        id.put("tipoDte", invoice.getTipoDte());
        id.put("numeroControl", invoice.getNumeroControl());
        id.put("codigoGeneracion", invoice.getCodigoGeneracion());
        id.put("tipoModelo", invoice.getTipoModelo());
        id.put("tipoOperacion", invoice.getTipoOperacion());
        id.put("tipoContingencia", invoice.getTipoContingencia());
        id.put("motivoContin", invoice.getMotivoContin());
        id.put("fecEmi", invoice.getFecEmi());
        id.put("horEmi", invoice.getHorEmi());
        id.put("tipoMoneda", invoice.getTipoMoneda());
        return id;
    }

    private List<Map<String, Object>> buildDocumentoRelacionado(Invoice invoice) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (InvoiceRelatedDocument d : invoice.getRelatedDocuments()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("tipoDocumento", d.getTipoDocumento());
            m.put("tipoGeneracion", d.getTipoGeneracion());
            m.put("numeroDocumento", d.getNumeroDocumento());
            m.put("fechaEmision", d.getFechaGeneracion());
            list.add(m);
        }
        return list;
    }

    private Map<String, Object> buildEmisor(InvoiceIssuer e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("nit", e.getNit());
        m.put("nrc", e.getNrc());
        m.put("nombre", e.getNombre());
        m.put("codActividad", e.getCodActividad());
        m.put("descActividad", e.getDescActividad());
        m.put("nombreComercial", e.getNombreComercial());
        m.put("tipoEstablecimiento", e.getTipoEstablecimiento());
        Map<String, Object> dir = new LinkedHashMap<>();
        dir.put("departamento", e.getDireccionDepartamento());
        dir.put("municipio", e.getDireccionMunicipio());
        dir.put("complemento", e.getDireccionComplemento());
        m.put("direccion", dir);
        m.put("telefono", e.getTelefono());
        m.put("correo", e.getCorreo());
        m.put("codEstableMH", e.getCodEstableMh());
        m.put("codEstable", e.getCodEstable());
        m.put("codPuntoVentaMH", e.getCodPuntoVentaMh());
        m.put("codPuntoVenta", e.getCodPuntoVenta());
        return m;
    }

    private Map<String, Object> buildReceptor(InvoiceReceiver r) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tipoDocumento", defaultTipoDocumento(r.getTipoDocumento()));
        m.put("nit", r.getNit());
        m.put("nrc", r.getNrc());
        m.put("nombre", r.getNombre());
        m.put("codActividad", r.getCodActividad());
        m.put("descActividad", r.getDescActividad());
        m.put("nombreComercial", r.getNombreComercial());
        Map<String, Object> dir = new LinkedHashMap<>();
        dir.put("departamento", r.getDireccionDepartamento());
        dir.put("municipio", r.getDireccionMunicipio());
        dir.put("complemento", r.getDireccionComplemento());
        m.put("direccion", dir);
        m.put("telefono", r.getTelefono());
        m.put("correo", r.getCorreo());
        m.put("numDocumento", r.getDocId());
        return m;
    }

    private List<Map<String, Object>> buildCuerpo(Invoice invoice) {
        List<Map<String, Object>> lines = new ArrayList<>();
        for (InvoiceLine line : invoice.getLines()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("numItem", line.getNumItem());
            m.put("tipoItem", line.getTipoItem());
            m.put("cantidad", line.getCantidad());
            m.put("uniMedida", line.getUniMedida());
            m.put("descripcion", line.getDescripcion());
            m.put("precioUni", line.getPrecioUni());
            m.put("montoDescu", nz(line.getMontoDescu()));
            m.put("ventaNoSuj", nz(line.getVentaNoSuj()));
            m.put("ventaExenta", nz(line.getVentaExenta()));
            m.put("ventaGravada", nz(line.getVentaGravada()));
            m.put("tributos", parseJsonArray(line.getTributosJson()));
            m.put("noGravado", nz(line.getNoGravado()));
            lines.add(m);
        }
        return lines;
    }

    private Map<String, Object> buildResumen(InvoiceSummary s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("totalNoSuj", nz(s.getTotalNoSuj()));
        m.put("totalExenta", nz(s.getTotalExenta()));
        m.put("totalGravada", nz(s.getTotalGravada()));
        m.put("subTotalVentas", nz(s.getSubTotalVentas()));
        m.put("descuNoSuj", nz(s.getDescuNoSuj()));
        m.put("descuExenta", nz(s.getDescuExenta()));
        m.put("descuGravada", nz(s.getDescuGravada()));
        m.put("tributos", parseJsonArray(s.getTributosJson()));
        m.put("subTotal", nz(s.getSubTotal()));
        m.put("ivaPerci", nz(s.getIvaPercibido()));
        m.put("ivaRete", nz(s.getIvaRetenido()));
        m.put("reteRenta", nz(s.getReteRenta()));
        m.put("montoTotalOperacion", nz(s.getMontoTotalOperacion()));
        m.put("totalPagar", nz(s.getTotalPagar()));
        m.put("totalLetras", s.getTotalLetras());
        m.put("condicionOperacion", s.getCondicionOperacion());
        m.put("pagos", parseJsonArray(s.getPagosJson()));
        return m;
    }

    private static BigDecimal nz(BigDecimal v) {
        return v == null ? BigDecimal.ZERO : v;
    }

    private Object parseJsonArray(String json) {
        if (json == null || json.isBlank()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readTree(json);
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private String defaultTipoDocumento(String tipoDocumento) {
        return tipoDocumento == null || tipoDocumento.isBlank() ? "13" : tipoDocumento;
    }
}
