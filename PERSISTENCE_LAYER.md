# Fineract Persistence Layer

This document explains how the persistence layer works in Fineract and how services are configured to use it.

---

## Overview

| Layer | Technology | Role |
|-------|------------|------|
| **ORM** | JPA 2.0 | Java Persistence API; entities, EntityManager, persistence context |
| **Provider** | EclipseLink | JPA implementation (not Hibernate) |
| **Data access** | Spring Data JPA | Repository interfaces, `JpaRepository`, query methods |
| **Transactions** | Spring `@Transactional` | Declarative transaction boundaries |
| **Database** | MySQL / PostgreSQL | Multi-tenant via routing datasource |

The runtime configuration is in **Java** (`JPAConfig`). The `persistence.xml` files under `jpa/static-weaving/module/` are used **only for static weaving** (EclipseLink bytecode weaving); entity discovery and datasource are configured in Spring.

---

## 1. Configuration

### 1.1 JPA configuration (`JPAConfig`)

**Location:** `fineract-provider/.../config/jpa/JPAConfig.java`

- **EntityManagerFactory**  
  Built with:
  - **DataSource:** `RoutingDataSource` (see below) so each request uses the correct tenant DB.
  - **Persistence unit name:** `jpa-pu`.
  - **Packages to scan:** `org.apache.fineract` (plus any from `EntityManagerFactoryCustomizer`).
  - **Depends on:** `tenantDatabaseUpgradeService`, `jsonbConverterContextInitializer` (so tenant DB and JSONB context are ready before the EMF is created).

- **JPA vendor:** `EclipseLinkJpaVendorAdapter` (EclipseLink-specific options).

- **EclipseLink settings:**
  - `WEAVING`: `static` (weaving done at build time).
  - `PERSISTENCE_CONTEXT_CLOSE_ON_COMMIT`: `true`.
  - `CACHE_SHARED_DEFAULT`: `false`.

- **Repositories:**  
  `@EnableJpaRepositories(basePackages = { "org.apache.fineract.**.domain", "org.apache.fineract.**.repository", "org.apache.fineract.command.persistence" })`  
  So Spring Data JPA repositories are picked up from those packages.

- **Auditing:**  
  `@EnableJpaAuditing` with an `AuditorAware<Long>` bean for created-by / last-modified-by.

- **Transaction manager:**  
  Provided by `JpaBaseConfiguration`; used for `@Transactional` and `TransactionTemplate`.

### 1.2 Routing datasource (multi-tenancy)

**Location:** `fineract-core/.../service/database/RoutingDataSource.java`, `RoutingDataSourceServiceFactory`, `TomcatJdbcDataSourcePerTenantService`

- **RoutingDataSource** is the `@Primary` DataSource used by the EntityManagerFactory.
- On each `getConnection()`, it asks `RoutingDataSourceServiceFactory` for the current `RoutingDataSourceService`, which returns the actual DataSource for the **current tenant**.
- Tenant is taken from **ThreadLocal**: `ThreadLocalContextUtil.getTenant()` → `FineractPlatformTenant` (and its connection details). So the tenant must be set earlier in the request (e.g. by tenant resolution filter/interceptor).
- Result: all JPA and JDBC access in that request goes to the correct tenant database without passing the tenant through every method.

### 1.3 Database type (MySQL vs PostgreSQL)

**Location:** `fineract-core/.../persistence/DatabaseSelectingPersistenceUnitPostProcessor.java`, `DatabaseTypeResolver`

- **DatabaseTypeResolver** determines whether the app is running against MySQL or PostgreSQL (e.g. from JDBC driver).
- **DatabaseSelectingPersistenceUnitPostProcessor** sets EclipseLink’s `TARGET_DATABASE` so the correct SQL/dialect is used.
- For DB-specific logic in code, use `DatabaseTypeResolver` (or existing helpers that use it) so native SQL or JSONB handling can branch by database. See also `.cursor/rules/jsonb-columns.mdc` for JSONB.

---

## 2. Entity layer

- **Packages:** Entities live under `org.apache.fineract.**`, typically in `...domain` packages (e.g. `portfolio.loanaccount.domain.Loan`).
- **Mapping:** JPA annotations on entities (`@Entity`, `@Table`, `@Column`, relationships, etc.). EclipseLink is the provider.
- **Static weaving:** Entity classes are listed in the module’s `persistence.xml` under `jpa/static-weaving/module/<module>/persistence.xml` so that the Gradle static-weaving step can weave them. New entities must be added there for weaving; runtime entity scan is still driven by `JPAConfig` package scanning.
- **Fetch strategy:** Prefer **LAZY** for relationships; EAGER is legacy and should be avoided for new mappings.
- **JSONB columns:** Use `JsonbStringAttributeConverter` and the pattern described in `.cursor/rules/jsonb-columns.mdc` for PostgreSQL JSONB (and MySQL JSON).

---

## 3. Repository layer

### 3.1 Spring Data JPA repositories

- **Interfaces** extend `JpaRepository<Entity, Id>` and optionally `JpaSpecificationExecutor<Entity>`.
- **Location:** Usually in the same module as the entity, in a `domain` or `repository` package (e.g. `LoanRepository` in `portfolio.loanaccount.domain`).
- **Scanned by:** `@EnableJpaRepositories` in `JPAConfig` (see above). No extra configuration is needed for a new repository interface in those packages.
- **Methods:**  
  - Standard CRUD from `JpaRepository`.  
  - Query methods by convention, or `@Query` (JPQL/native).  
  - Specifications via `JpaSpecificationExecutor` where needed.

Example:

```java
public interface LoanRepository extends JpaRepository<Loan, Long>, JpaSpecificationExecutor<Loan> {
    Optional<Loan> findByExternalId(ExternalId externalId);
    // ...
}
```

### 3.2 Repository wrappers

- Many domains have a **wrapper** class (e.g. `LoanRepositoryWrapper`) that:
  - Injects the Spring Data `XxxRepository`.
  - Adds **null/not-found handling** (e.g. `findOneWithNotFoundDetection(id)` throws a domain exception instead of returning empty).
  - Adds **lazy-initialization** where needed (e.g. `initializeLazyCollections()` so that lazy collections are loaded in the same transaction).
  - Exposes **save** and **saveAndFlush** so callers get a consistent API and optional flush semantics.
- Wrappers are **`@Service`** and **`@RequiredArgsConstructor`** (or explicit constructor) so they are Spring beans and can inject the underlying repository.
- **Services use the wrapper** (e.g. `LoanRepositoryWrapper`), not the raw `LoanRepository`, when they need “find or throw” or “save and flush” behavior.

Example (conceptually):

```java
@Service
@RequiredArgsConstructor
public class LoanRepositoryWrapper {
    private final LoanRepository repository;

    @Transactional(readOnly = true)
    public Loan findOneWithNotFoundDetection(Long id) {
        return repository.findById(id).orElseThrow(() -> new LoanNotFoundException(id));
    }

    public Loan saveAndFlush(Loan loan) {
        return repository.saveAndFlush(loan);
    }
    // ...
}
```

---

## 4. Service layer: how to use the persistence layer

### 4.1 Making a service use persistence

1. **Annotate the service class**
   - `@Service` so it is a Spring bean.
   - `@RequiredArgsConstructor` (Lombok) or a constructor to inject dependencies.

2. **Inject repositories or wrappers**
   - Prefer **repository wrappers** where they exist (e.g. `LoanRepositoryWrapper`, `SesionComiteRepository` + any wrapper).
   - Otherwise inject the **Spring Data repository** (e.g. `LoanTransactionRepository`) or other JPA-backed beans.
   - Do **not** inject `EntityManager` unless you have a clear need; prefer repositories and wrappers.

3. **Define transaction boundaries**
   - **`@Transactional`** on the class or on public methods that perform writes or multi-step reads that must be consistent.
   - Use **`@Transactional(readOnly = true)`** for read-only operations (allows optimizations and documents intent).
   - Default propagation is `REQUIRED`: method runs in the current transaction or starts a new one. That’s usually what you want.

4. **Use wrapper/repository APIs**
   - **Read:** e.g. `loanRepositoryWrapper.findOneWithNotFoundDetection(loanId)` so missing data becomes a clear exception.
   - **Write:** `repository.save(entity)` or `repository.saveAndFlush(entity)` (see below). Wrappers often expose `saveAndFlush` for when you need immediate DB sync.

### 4.2 Example: service that uses persistence

```java
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessComiteOtorgamientoLoansServiceImpl implements ProcessComiteOtorgamientoLoansService {

    private final LoanRepositoryWrapper loanRepositoryWrapper;
    private final LoanTransactionRepository loanTransactionRepository;
    // ... other dependencies

    @Override
    @Transactional
    public ProcessComiteOtorgamientoResult process(SesionComite session, List<Long> approvedLoanIds) {
        // ...
        Loan loan = loanRepositoryWrapper.findOneWithNotFoundDetection(loanId);
        // ... business logic ...
        loan.setNetDisbursalAmount(disbursementAmount);
        loan.setComitePreProcessed(true);
        loanRepositoryWrapper.saveAndFlush(loan);
        // ...
    }
}
```

- **Tenant:** Already set in `ThreadLocalContextUtil` by the time the API is invoked; `RoutingDataSource` uses it, so no tenant parameter is needed in the service.
- **Transaction:** One transaction for the whole `process(...)` call; all reads/writes are in that transaction and commit or roll back together.

### 4.3 save vs saveAndFlush

- **save(entity)**  
  Marks the entity as persistent and schedules the INSERT/UPDATE in the persistence context. The SQL may be sent at flush time or at commit time.

- **saveAndFlush(entity)**  
  Same as save, but **immediately flushes** the persistence context to the database. Use it when:
  - You need the DB to see the change before the next step (e.g. triggers, or a subsequent read that must see the update).
  - You want constraint or DB errors to surface immediately rather than at commit.

For critical updates (e.g. comité pre-processing flags and amounts), the codebase often uses **saveAndFlush** so the row is updated and visible in the same transaction.

---

## 5. Checklist for new or updated services

- [ ] Service class has `@Service` and is in a package scanned by Spring (e.g. under `org.apache.fineract`).
- [ ] Dependencies (repositories, wrappers, other services) are injected via constructor (e.g. `@RequiredArgsConstructor` + `private final`).
- [ ] Public methods that touch the DB have a clear transaction boundary: `@Transactional` for writes or multi-step reads, `@Transactional(readOnly = true)` for read-only.
- [ ] Use **repository wrappers** where they exist (e.g. `LoanRepositoryWrapper`); use raw repositories only when you don’t need “not found” handling or wrapper helpers.
- [ ] For new entities: add the entity class to the appropriate module `persistence.xml` for static weaving; keep relationships LAZY where possible; use the JSONB converter for JSONB columns (see `.cursor/rules/jsonb-columns.mdc`).
- [ ] For new repositories: define an interface extending `JpaRepository` (and optionally `JpaSpecificationExecutor`) in a package under `org.apache.fineract.**.domain` or `**.repository` so `JPAConfig`’s `@EnableJpaRepositories` picks it up.
- [ ] Don’t rely on tenant in method signatures for DB access; tenant is provided by the request context and `RoutingDataSource`.

---

## 6. Related documentation

- **Database support, tenant security, schema migration:** `fineract-doc/.../architecture/persistence.adoc`
- **JSONB columns:** `.cursor/rules/jsonb-columns.mdc`
- **Static weaving:** `fineract-core/STATIC_WEAVING.md` (if present) and `static-weaving.gradle`
