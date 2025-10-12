# Scripts

This directory contains utility scripts for the Modal project.

## generate-supabase-keys.sh

Generates secure Supabase JWT keys and updates configuration files.

### What it does

1. **Generates a random JWT secret** (32 bytes, base64-encoded)
2. **Creates ANON_KEY** - JWT token for anonymous access
3. **Creates SERVICE_ROLE_KEY** - JWT token for service-level access
4. **Generates a strong Postgres password** (24 bytes, base64-encoded)
5. **Updates .env file** with the generated keys
6. **Updates Kong configuration** (supabase/kong.yml) with the new keys

### Prerequisites

- `openssl` - For generating secure random values and creating JWTs
- `base64` - For encoding values
- `bash` 4.0+

Both tools are typically pre-installed on macOS and Linux.

### Usage

#### First Time Setup

```bash
# Make the script executable (only needed once)
chmod +x scripts/generate-supabase-keys.sh

# Run the script
./scripts/generate-supabase-keys.sh
```

If `.env` doesn't exist, the script will create it from `.env.example`.

#### Regenerate Keys

```bash
./scripts/generate-supabase-keys.sh
```

The script will:
- Ask for confirmation before updating existing `.env`
- Create backups of both `.env` and `kong.yml` before making changes
- Display a summary of what was generated

#### Non-Interactive Mode

To just print the keys without updating files:

```bash
./scripts/generate-supabase-keys.sh
# When prompted, press 'N' to decline updating .env
```

### What Gets Updated

#### 1. .env file

The following environment variables are updated:

```bash
JWT_SECRET=<generated-secret>
ANON_KEY=<generated-jwt-token>
SERVICE_ROLE_KEY=<generated-jwt-token>
POSTGRES_PASSWORD=<generated-password>
```

#### 2. Kong Configuration (supabase/kong.yml)

Updates the API gateway configuration with the new keys:
- Replaces the `anon` consumer's key
- Replaces the `service_role` consumer's key

### Backups

The script automatically creates timestamped backups:

```
.env.backup.20241012_143022
kong.yml.backup.20241012_143022
```

These are safe to delete once you've verified everything works.

### After Running the Script

**Restart Docker services** to apply the new keys:

```bash
docker-compose down
docker-compose up -d
```

Or if services are already running:

```bash
docker-compose restart
```

### Security Notes

1. **Never commit .env to version control** - It's already in `.gitignore`
2. **Regenerate keys for production** - Don't use the same keys across environments
3. **Keep backups secure** - The backup files contain sensitive keys
4. **JWT tokens expire in 2099** - Consider shorter expiry for production

### JWT Token Structure

The generated JWTs have this structure:

**Header:**
```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

**Payload (anon):**
```json
{
  "iss": "supabase",
  "role": "anon",
  "iat": <current-timestamp>,
  "exp": 4102444800
}
```

**Payload (service_role):**
```json
{
  "iss": "supabase",
  "role": "service_role",
  "iat": <current-timestamp>,
  "exp": 4102444800
}
```

The tokens are signed with the JWT_SECRET using HMAC-SHA256.

### Troubleshooting

#### "openssl: command not found"

Install OpenSSL:
- **macOS**: `brew install openssl`
- **Linux**: `sudo apt-get install openssl` or `sudo yum install openssl`

#### "Permission denied"

Make the script executable:
```bash
chmod +x scripts/generate-supabase-keys.sh
```

#### Keys not working after update

1. Check that .env was actually updated: `cat .env | grep ANON_KEY`
2. Restart Docker containers: `docker-compose restart`
3. Check Kong logs: `docker-compose logs kong`
4. Verify JWT_SECRET matches in both .env and auth service

#### Want to use custom JWT secret

Edit `.env` directly and set `JWT_SECRET` to your value, then run:
```bash
# Manually set JWT_SECRET in .env first
./scripts/generate-supabase-keys.sh
```

The script will use your JWT_SECRET or generate a new one.

### Advanced Usage

#### Generate keys for different environments

```bash
# Development
./scripts/generate-supabase-keys.sh

# Staging (copy to staging server)
scp scripts/generate-supabase-keys.sh user@staging:/path/to/modal/scripts/
ssh user@staging "cd /path/to/modal && ./scripts/generate-supabase-keys.sh"

# Production
# Same as staging, but use different servers
```

#### Integrate with CI/CD

```yaml
# Example GitHub Actions workflow
- name: Generate Supabase Keys
  run: |
    ./scripts/generate-supabase-keys.sh
  env:
    CI: true
```

For CI/CD, you may want to:
1. Store JWT_SECRET in secrets manager (AWS Secrets, GitHub Secrets, etc.)
2. Inject it into .env before running the script
3. Avoid interactive prompts

### Related Files

- `/.env` - Environment variables (generated/updated by script)
- `/.env.example` - Template for .env
- `/supabase/kong.yml` - Kong API Gateway config (updated by script)
- `/supabase/kong.yml.template` - Template for kong.yml
- `/docker-compose.yml` - Docker services configuration
- `/DOCKER.md` - Docker setup documentation

### Manual Key Generation

If you need to manually generate keys without the script:

```bash
# Generate JWT secret
openssl rand -base64 32

# Generate Postgres password
openssl rand -base64 24

# For JWTs, you'll need to:
# 1. Create the header and payload JSON
# 2. Base64url encode them
# 3. Sign with HMAC-SHA256
# 4. Base64url encode the signature
# (The script automates this - recommended to use it)
```

### Support

For issues:
1. Check the Troubleshooting section above
2. Review DOCKER.md for Docker-specific issues
3. Check script output for error messages
4. Open an issue in the repository
