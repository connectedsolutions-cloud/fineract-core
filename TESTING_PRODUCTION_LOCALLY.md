# Testing Production Settings Locally

It's **highly recommended** to test your application with production-like settings locally before deploying to production. This helps catch configuration issues, environment variable problems, and ensures your custom settings work correctly.

## Why Test Production Settings Locally?

1. **Catch Configuration Issues Early**: Discover problems before deploying
2. **Validate Environment Variables**: Ensure all custom variables are set correctly
3. **Test Production Behavior**: Some features behave differently in production mode
4. **Security Settings**: Verify that security settings (like `FINERACT_INSECURE_HTTP_CLIENT=false`) work correctly
5. **Database Connections**: Test with production-like database configurations

## Quick Start

### Option 1: Using `prodLikeRun` Task (Recommended)

1. **Create production-like environment file**:
   ```bash
   cd fineract-core
   cp env.production.local.template .env.production.local
   ```

2. **Edit `.env.production.local`** with your local database settings:
   ```bash
   nano .env.production.local
   ```
   
   Update at minimum:
   - `FINERACT_HIKARI_PASSWORD` - Your local database password
   - `FINERACT_DEFAULT_TENANTDB_PWD` - Your local tenant database password
   - Database connection URLs if using non-standard ports

3. **Run with production-like settings**:
   ```bash
   ./gradlew prodLikeRun
   ```

4. **Verify it's running in production mode**:
   ```bash
   curl -k https://localhost:8443/fineract-provider/actuator/info
   ```
   
   Check the logs - you should see:
   - `Running in PRODUCTION-LIKE mode for local testing`
   - `Spring Profile: production`
   - `Insecure HTTP Client: false`

### Option 2: Using `devRun` with Production Environment Variables

You can also use `devRun` but override environment variables:

1. **Create `.env` file** (or modify existing one):
   ```bash
   cd fineract-core
   ```

2. **Set production-like variables in `.env`**:
   ```bash
   export SPRING_PROFILES_ACTIVE=production
   export FINERACT_INSECURE_HTTP_CLIENT=false
   # ... other production settings
   ```

3. **Run**:
   ```bash
   ./gradlew devRun
   ```

## Key Differences: Development vs Production

| Setting | Development (`devRun`) | Production (`prodLikeRun`) |
|---------|----------------------|---------------------------|
| Spring Profiles | `test,diagnostics` | `production` |
| Insecure HTTP Client | `true` | `false` |
| Debug Options | Enabled | Disabled |
| JVM Args | Includes debug port | Production-optimized |
| Quality Checks | Skipped | Skipped (same) |

## What to Test

When running with production-like settings, test:

1. **Application Startup**
   - Does it start without errors?
   - Are all environment variables loaded correctly?
   - Are database connections working?

2. **API Endpoints**
   - Test key API endpoints
   - Verify authentication works
   - Check that SSL is working

3. **Custom Environment Variables**
   - Verify all your custom variables are accessible
   - Test that they're being used correctly

4. **Database Operations**
   - Create/read/update operations
   - Verify tenant database connections

5. **Health Checks**
   ```bash
   curl -k https://localhost:8443/fineract-provider/actuator/health
   ```

## Troubleshooting

### Application Won't Start

1. **Check environment variables**:
   ```bash
   # Verify .env.production.local is being loaded
   cat .env.production.local
   ```

2. **Check database connection**:
   - Ensure database is running
   - Verify credentials are correct
   - Check database exists: `fineract_tenants` and `fineract_default`

3. **Check logs**:
   ```bash
   tail -f build/fineract/logs/fineract.log
   ```

### SSL Certificate Issues

If you see SSL errors, this is expected in production mode. The application uses a self-signed certificate for local development. In production, you'll use proper certificates.

### Environment Variables Not Loading

- Ensure `.env.production.local` exists in `fineract-core/` directory
- Check file format (no spaces around `=`)
- Verify no syntax errors in the file

### Database Connection Errors

- Verify database is running: `mysql -u root -p`
- Check database exists: `SHOW DATABASES;`
- Verify credentials match your `.env.production.local`

## Before Deploying to Production

✅ **Checklist**:

- [ ] Application starts successfully with `prodLikeRun`
- [ ] All API endpoints work correctly
- [ ] Custom environment variables are accessible
- [ ] Database connections work
- [ ] Health checks pass
- [ ] No errors in logs
- [ ] SSL is working (even with self-signed cert locally)
- [ ] `FINERACT_INSECURE_HTTP_CLIENT=false` is set
- [ ] `SPRING_PROFILES_ACTIVE=production` is set

## Environment File Priority

When using `prodLikeRun`:
1. First tries to load `.env.production.local`
2. Falls back to `.env` if `.env.production.local` doesn't exist
3. System environment variables override file variables

## Next Steps

After successfully testing locally with production settings:

1. Review the [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md) for deployment steps
2. Use the same environment variables in your production `.env` file
3. Deploy using the provided deployment scripts

## Example: Complete Testing Workflow

```bash
# 1. Set up production-like environment
cd fineract-core
cp env.production.local.template .env.production.local

# 2. Edit with your settings
nano .env.production.local

# 3. Ensure databases exist
./gradlew createDB -PdbName=fineract_tenants
./gradlew createDB -PdbName=fineract_default

# 4. Run with production-like settings
./gradlew prodLikeRun

# 5. In another terminal, test the API
curl -k https://localhost:8443/fineract-provider/actuator/health
curl -k https://localhost:8443/fineract-provider/actuator/info

# 6. Test a real API endpoint
curl -k -X GET \
  https://localhost:8443/fineract-provider/api/v1/clients \
  -H 'Fineract-Platform-TenantId: default' \
  -H 'Authorization: Basic bWlmb3M6cGFzc3dvcmQ='

# 7. Check logs for any issues
tail -f build/fineract/logs/fineract.log
```

## Notes

- The `prodLikeRun` task still skips quality checks (like `devRun`) for faster startup
- It uses production Spring profiles and settings
- Local database is fine for testing - you don't need production database
- SSL certificate warnings are expected with self-signed certs locally
- This is for **testing**, not actual production deployment
