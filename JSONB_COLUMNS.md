# JSONB Columns in Fineract

This document explains how to work with **PostgreSQL JSONB** (and MySQL JSON) columns in JPA entities. The Java/Spring/EclipseLink stack does not handle JSONB natively, so we use a custom converter.

---

## Why a converter?

- **JPA** has no standard mapping for JSONB.
- **EclipseLink** does not ship built-in JSONB support for PostgreSQL.
- **JDBC** binds `String` as `VARCHAR` by default. PostgreSQL then rejects it:  
  `column "x" is of type jsonb but expression is of type character varying`.

The **`JsonbStringAttributeConverter`** bridges this: we keep the Java field as `String` (JSON), and the converter turns it into a PostgreSQL `PGobject` with type `jsonb` so the driver sends real JSONB.

---

## Components

| Component | Location | Role |
|-----------|----------|------|
| **JsonbStringAttributeConverter** | `fineract-core/.../persistence/converter/JsonbStringAttributeConverter.java` | Converts `String` ↔ JSONB via `PGobject` on PostgreSQL; pass-through on MySQL |
| **JsonbConverterContext** | `.../persistence/converter/JsonbConverterContext.java` | Static holder for `DatabaseTypeResolver` (JPA instantiates converters without DI) |
| **JsonbConverterContextInitializer** | `.../persistence/converter/JsonbConverterContextInitializer.java` | Spring bean that sets the context at startup |

The converter is registered in `fineract-provider`’s `persistence.xml` and the EMF depends on `jsonbConverterContextInitializer`.

---

## Adding a JSONB column to an entity

### 1. Entity mapping

Use a `String` attribute and `@Convert` with the JSONB converter:

```java
@Column(name = "my_json_column", columnDefinition = "json")
@Convert(converter = JsonbStringAttributeConverter.class)
private String myJsonColumn;
```

- **Java type**: always `String` (the raw JSON, e.g. `"[1,2,3]"`, `"{\"a\":1}"`).
- **`columnDefinition = "json"`**: generic; actual DB type comes from migrations (see below).

### 2. Database migrations

- **PostgreSQL**: use `JSONB` in Liquibase.
- **MySQL**: use `JSON`.

Example (Liquibase):

```xml
<!-- PostgreSQL -->
<column name="my_json_column" type="JSONB"/>

<!-- MySQL -->
<column name="my_json_column" type="JSON"/>
```

### 3. Persist / read

- **Write**: set the field to a **valid JSON string** (e.g. `entity.setMyJsonColumn("[1,2,3]")`). The converter sends it as JSONB.
- **Read**: the converter maps JSONB back to `String`; parse with Gson/Jackson as needed.

---

## Null handling (important)

### Problem

If the converter returns `null` for null attributes, JPA may **skip** the converter and bind `null` using the attribute type (`String`), i.e. as **VARCHAR**. PostgreSQL then errors:  
`column "x" is of type jsonb but expression is of type character varying`.

### Solution

The converter **always** uses `PGobject` for PostgreSQL, **including when the value is null**:

- `attribute == null` → `pg.setType("jsonb")` and `pg.setValue(null)`.
- The driver sends a **JSONB NULL**, not VARCHAR.

So you **must** use the converter for every JSONB column. Do not bypass it or return plain `null` for PostgreSQL.

### In your code

- **Storing null**: `entity.setMyJsonColumn(null)` is fine. The converter handles it.
- **Storing empty**: use either `null` or a valid JSON literal (`"[]"`, `"{}"`, `"null"`) depending on your domain meaning.
- **Reading**: `convertToEntityAttribute` returns `null` when the DB value is null.

---

## Checklist for new JSONB columns

1. Add the column in the entity as `String` with `@Convert(converter = JsonbStringAttributeConverter.class)`.
2. Add Liquibase changes: `JSONB` for PostgreSQL, `JSON` for MySQL.
3. Ensure the converter is used (no manual JDBC or raw SQL that bypasses it).
4. Use `null` or valid JSON strings only; the converter handles nulls correctly.

---

## Debug logging

To see exactly what is sent to the DB for JSONB columns:

```properties
# application.properties
logging.level.org.apache.fineract.infrastructure.core.persistence.converter=DEBUG
```

You’ll get logs like:

```
[JsonbStringAttributeConverter] convertToDatabaseColumn: sending as JSONB, value=[1,2,3]
[JsonbStringAttributeConverter] convertToDatabaseColumn: sending as JSONB, value=null
```

---

## Example: `SesionComite`

`SesionComite` uses the converter for `integrantes`, `selection`, and `output`:

```java
@Column(name = "integrantes", columnDefinition = "json")
@Convert(converter = JsonbStringAttributeConverter.class)
private String integrantes;

@Column(name = "selection", columnDefinition = "json")
@Convert(converter = JsonbStringAttributeConverter.class)
private String selection;

@Column(name = "output", columnDefinition = "json")
@Convert(converter = JsonbStringAttributeConverter.class)
private String output;
```

On create, `selection` and `output` are `null`; the converter still sends them as JSONB NULL, so no “character varying” errors.

---

## Summary

| Scenario | Java | DB (PostgreSQL) |
|----------|------|------------------|
| Non-null JSON | `"[1,2,3]"` | `PGobject` type `jsonb`, value `[1,2,3]` |
| Null | `null` | `PGobject` type `jsonb`, value `null` (JSONB NULL) |
| MySQL | Same `String` / `null` | Pass-through; column type `JSON` |

Always use `JsonbStringAttributeConverter` for JSONB columns, and never return raw `null` from the converter on PostgreSQL—use `PGobject` with `setValue(null)` instead.
