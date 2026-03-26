import * as p from "@clack/prompts";
import chalk from "chalk";
import { execSync } from "child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderLogo, SETUP_SUBTITLE } from "../constants";

function getProjectRoot(): string {
  const cliDir = import.meta.dir ?? dirname(fileURLToPath(import.meta.url));
  return join(cliDir, "..", "..", "..", "..");
}

function base64urlEncode(input: string): string {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

function createJWT(role: string, secret: string, expiry: number): string {
  const header = { alg: "HS256", typ: "JWT" };
  const payload = {
    iss: "supabase",
    role,
    iat: Math.floor(Date.now() / 1000),
    exp: expiry,
  };

  const headerBase64 = base64urlEncode(JSON.stringify(header));
  const payloadBase64 = base64urlEncode(JSON.stringify(payload));

  const crypto = require("crypto");
  const signature = crypto
    .createHmac("sha256", secret)
    .update(`${headerBase64}.${payloadBase64}`)
    .digest("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");

  return `${headerBase64}.${payloadBase64}.${signature}`;
}

function updateEnvVar(filePath: string, key: string, value: string) {
  if (!existsSync(filePath)) {
    writeFileSync(filePath, `${key}=${value}\n`);
    return;
  }

  const content = readFileSync(filePath, "utf-8");
  const lines = content.split("\n");
  let found = false;

  const updated = lines.map((line) => {
    if (line.startsWith(`${key}=`)) {
      found = true;
      return `${key}=${value}`;
    }
    return line;
  });

  if (!found) {
    updated.push(`${key}=${value}`);
  }

  writeFileSync(filePath, updated.join("\n") + "\n");
}

function readEnvValue(filePath: string, key: string): string {
  if (!existsSync(filePath)) {
    return "";
  }
  const content = readFileSync(filePath, "utf-8");
  const match = content.match(new RegExp(`^${key}=(.+)$`, "m"));
  return match?.[1] ?? "";
}

export async function setupCommand() {
  console.log(renderLogo(SETUP_SUBTITLE));
  p.intro(chalk.bgCyan.black(" setup "));
  const setupStartedAt = Date.now();
  p.log.step("Modal Environment Configuration");

  const projectRoot = getProjectRoot();
  const dockerEnv = join(projectRoot, "docker", ".env");
  const supabaseEnv = join(projectRoot, "docker", "supabase", ".env");
  const apiEnv = join(projectRoot, "apps", "api", ".env");
  const iosConfig = join(projectRoot, "apps", "milo", "Config.xcconfig");

  // Check for openssl
  p.log.step("Checking prerequisites");
  console.log("");
  try {
    execSync("which openssl", { stdio: "pipe" });
    p.log.success("openssl found");
  } catch {
    p.log.error("openssl is required but not installed");
    process.exit(1);
  }

  // JWT Configuration
  p.log.step("JWT Configuration");

  let jwtSecret: string = "";
  const existingJwtSecret = readEnvValue(dockerEnv, "JWT_SECRET");
  const updateJwt = await p.confirm({
    message: "Update JWT configuration?",
    initialValue: true,
  });
  if (p.isCancel(updateJwt)) return;

  if (updateJwt) {
    if (existingJwtSecret) {
      const useExisting = await p.confirm({
        message: "Found existing JWT_SECRET. Use existing?",
        initialValue: true,
      });
      if (p.isCancel(useExisting)) return;
      if (useExisting) {
        jwtSecret = existingJwtSecret;
      }
    }
    if (!jwtSecret) {
      jwtSecret = execSync("openssl rand -base64 32", {
        encoding: "utf-8",
      }).trim();
      p.log.success("Generated new JWT secret");
    } else {
      p.log.success("Using existing JWT secret");
    }
  } else {
    if (existingJwtSecret) {
      jwtSecret = existingJwtSecret;
      p.log.success("Keeping existing JWT secret");
    } else {
      p.log.warn("No existing JWT_SECRET found; generating a new one.");
      jwtSecret = execSync("openssl rand -base64 32", {
        encoding: "utf-8",
      }).trim();
      p.log.success("Generated new JWT secret");
    }
  }

  // Generate keys (year 2099 expiry)
  const expiryDate = 4102444800;
  const existingAnonKey = readEnvValue(dockerEnv, "SUPABASE_ANON_KEY");
  const existingServiceRoleKey = readEnvValue(
    dockerEnv,
    "SUPABASE_SERVICE_ROLE_KEY",
  );
  const anonKey =
    !updateJwt && existingAnonKey
      ? existingAnonKey
      : createJWT("anon", jwtSecret, expiryDate);
  const serviceRoleKey =
    !updateJwt && existingServiceRoleKey
      ? existingServiceRoleKey
      : createJWT("service_role", jwtSecret, expiryDate);
  p.log.success("Generated ANON_KEY and SERVICE_ROLE_KEY");
  console.log("");

  // OAuth Configuration
  p.log.step("OAuth Configuration");
  console.log("");

  let googleClientId = "";
  let googleClientSecret = "";
  let spotifyClientId = "";
  let spotifyClientSecret = "";
  let sonioxApiKey = "";

  if (existsSync(dockerEnv)) {
    const content = readFileSync(dockerEnv, "utf-8");
    const googleMatch = content.match(/^GOOGLE_CLIENT_ID=(.+)$/m);
    if (googleMatch) googleClientId = googleMatch[1];
    const googleSecretMatch = content.match(/^GOOGLE_CLIENT_SECRET=(.+)$/m);
    if (googleSecretMatch) googleClientSecret = googleSecretMatch[1];
    const spotifyMatch = content.match(/^SPOTIFY_CLIENT_ID=(.+)$/m);
    if (spotifyMatch) spotifyClientId = spotifyMatch[1];
    const spotifySecretMatch = content.match(/^SPOTIFY_CLIENT_SECRET=(.+)$/m);
    if (spotifySecretMatch) spotifyClientSecret = spotifySecretMatch[1];
    const sonioxMatch = content.match(/^SONIOX_API_KEY=(.+)$/m);
    if (sonioxMatch) sonioxApiKey = sonioxMatch[1];
  }

  const updateOAuth = await p.confirm({
    message: "Update OAuth credentials?",
    initialValue: false,
  });

  if (!p.isCancel(updateOAuth) && updateOAuth) {
    googleClientId = (await p.text({
      message: "Google Client ID",
      initialValue: googleClientId,
    })) as string;
    if (p.isCancel(googleClientId)) return;

    googleClientSecret = (await p.password({
      message: "Google Client Secret",
    })) as string;
    if (p.isCancel(googleClientSecret)) return;

    spotifyClientId = (await p.text({
      message: "Spotify Client ID",
      initialValue: spotifyClientId,
    })) as string;
    if (p.isCancel(spotifyClientId)) return;

    spotifyClientSecret = (await p.password({
      message: "Spotify Client Secret",
    })) as string;
    if (p.isCancel(spotifyClientSecret)) return;

    sonioxApiKey = (await p.text({
      message: "Soniox API Key",
      initialValue: sonioxApiKey,
    })) as string;
    if (p.isCancel(sonioxApiKey)) return;
  }
  p.log.success("OAuth configuration complete");
  console.log("");

  // Generate security keys
  p.log.step("Generating security keys");
  const updateSecurityKeys = await p.confirm({
    message: "Regenerate security keys?",
    initialValue: false,
  });
  if (p.isCancel(updateSecurityKeys)) return;

  const existingSecretKeyBase = readEnvValue(dockerEnv, "SECRET_KEY_BASE");
  const existingVaultEncKey = readEnvValue(dockerEnv, "VAULT_ENC_KEY");
  const existingLogflarePublicToken = readEnvValue(
    dockerEnv,
    "LOGFLARE_PUBLIC_ACCESS_TOKEN",
  );
  const existingLogflarePrivateToken = readEnvValue(
    dockerEnv,
    "LOGFLARE_PRIVATE_ACCESS_TOKEN",
  );

  const shouldReuseSecurityKeys =
    !updateSecurityKeys &&
    existingSecretKeyBase &&
    existingVaultEncKey &&
    existingLogflarePublicToken &&
    existingLogflarePrivateToken;

  const secretKeyBase = shouldReuseSecurityKeys
    ? existingSecretKeyBase
    : execSync("openssl rand -base64 48", { encoding: "utf-8" }).trim();
  const vaultEncKey = shouldReuseSecurityKeys
    ? existingVaultEncKey
    : execSync("openssl rand -base64 24", { encoding: "utf-8" }).trim();
  const logflarePublicToken = shouldReuseSecurityKeys
    ? existingLogflarePublicToken
    : execSync("openssl rand -hex 16", { encoding: "utf-8" }).trim();
  const logflarePrivateToken = shouldReuseSecurityKeys
    ? existingLogflarePrivateToken
    : execSync("openssl rand -hex 16", { encoding: "utf-8" }).trim();

  if (shouldReuseSecurityKeys) {
    p.log.success("Keeping existing security keys");
  } else {
    p.log.success("Generated security keys");
  }

  // Create docker/.env
  p.log.step("Creating docker/.env");
  const writeDockerEnv = await p.confirm({
    message: "Update docker/.env?",
    initialValue: true,
  });
  if (p.isCancel(writeDockerEnv)) return;

  const dockerEnvContent = `# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_PASSWORD=postgres

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Supabase Configuration
SUPABASE_URL=http://localhost:8000
SUPABASE_PUBLIC_URL=http://localhost:8000
SUPABASE_KONG_URL=http://kong:8000
SUPABASE_ANON_KEY=${anonKey}
SUPABASE_SERVICE_ROLE_KEY=${serviceRoleKey}

# JWT Configuration
JWT_SECRET=${jwtSecret}
JWT_ALGORITHM=HS256
JWT_EXPIRY=3600
ACCESS_TOKEN_EXPIRE_MINUTES=30

# API Configuration
DEBUG=false
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API
API_PORT=8080
API_EXTERNAL_URL=http://localhost:8000
SITE_URL=http://localhost:3000
ADDITIONAL_REDIRECT_URLS=milo://spotify/callback
DISABLE_SIGNUP=false

# Email Configuration
ENABLE_EMAIL_SIGNUP=true
ENABLE_EMAIL_AUTOCONFIRM=true
ENABLE_ANONYMOUS_USERS=false

# Phone Configuration
ENABLE_PHONE_SIGNUP=false
ENABLE_PHONE_AUTOCONFIRM=false

# SMTP Configuration
SMTP_ADMIN_EMAIL=admin@example.com
SMTP_SENDER_NAME=Modal
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=dummy
SMTP_PASS=dummy

# Mailer URL paths
MAILER_URLPATHS_INVITE=/auth/v1/verify
MAILER_URLPATHS_CONFIRMATION=/auth/v1/verify
MAILER_URLPATHS_RECOVERY=/auth/v1/verify
MAILER_URLPATHS_EMAIL_CHANGE=/auth/v1/verify

# PostgREST Configuration
PGRST_DB_SCHEMAS=public,storage,graphql_public

# Image Proxy
IMGPROXY_ENABLE_WEBP_DETECTION=true

# Studio Configuration
STUDIO_DEFAULT_ORGANIZATION=Default Organization
STUDIO_DEFAULT_PROJECT=Default Project
DASHBOARD_USERNAME=supabase
DASHBOARD_PASSWORD=supabase

# Analytics
LOGFLARE_PUBLIC_ACCESS_TOKEN=${logflarePublicToken}
LOGFLARE_PRIVATE_ACCESS_TOKEN=${logflarePrivateToken}
LOGFLARE_API_KEY=${logflarePrivateToken}

# Functions
FUNCTIONS_VERIFY_JWT=true

# Pooler Configuration
POOLER_TENANT_ID=pooler-dev
POOLER_DEFAULT_POOL_SIZE=20
POOLER_MAX_CLIENT_CONN=100
POOLER_DB_POOL_SIZE=10
POOLER_PROXY_PORT_TRANSACTION=6543

# Security Keys
SECRET_KEY_BASE=${secretKeyBase}
VAULT_ENC_KEY=${vaultEncKey}

# Kong Ports
KONG_HTTP_PORT=8000
KONG_HTTPS_PORT=8443

# Docker
DOCKER_SOCKET_LOCATION=/var/run/docker.sock

# OpenAI (optional)
OPENAI_API_KEY=

# OAuth - Google
ENABLE_GOOGLE_OAUTH=true
GOOGLE_CLIENT_ID=${googleClientId}
GOOGLE_CLIENT_SECRET=${googleClientSecret}
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/v1/callback
GOOGLE_SKIP_NONCE_CHECK=true

# OAuth - Apple
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# OAuth - Spotify
SPOTIFY_CLIENT_ID=${spotifyClientId}
SPOTIFY_CLIENT_SECRET=${spotifyClientSecret}
SPOTIFY_REDIRECT_URI=milo://spotify/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=http://localhost:8080/api/v1/integrations/gmail/callback

# Soniox Speech-to-Text
SONIOX_API_KEY=${sonioxApiKey}
`;

  if (writeDockerEnv) {
    writeFileSync(dockerEnv, dockerEnvContent);
    p.log.success("Created docker/.env");
  } else {
    p.log.warn("Skipped docker/.env update");
  }
  console.log("");

  // Create apps/api/.env
  p.log.step("Creating apps/api/.env");
  const writeApiEnv = await p.confirm({
    message: "Update apps/api/.env?",
    initialValue: true,
  });
  if (p.isCancel(writeApiEnv)) return;

  const apiEnvContent = `# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@0.0.0.0:5432/postgres

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# JWT Configuration
JWT_SECRET=${jwtSecret}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Supabase Configuration
SUPABASE_URL=http://localhost:8000
SUPABASE_ANON_KEY=${anonKey}
SUPABASE_SERVICE_ROLE_KEY=${serviceRoleKey}

# Google OAuth
GOOGLE_CLIENT_ID=${googleClientId}
GOOGLE_CLIENT_SECRET=${googleClientSecret}
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback

# Apple OAuth
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# Spotify OAuth
SPOTIFY_CLIENT_ID=${spotifyClientId}
SPOTIFY_CLIENT_SECRET=${spotifyClientSecret}
SPOTIFY_REDIRECT_URI=milo://spotify/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=http://localhost:8080/api/v1/integrations/gmail/callback

# Soniox Speech-to-Text
SONIOX_API_KEY=${sonioxApiKey}

# Application Settings
DEBUG=True
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API
`;

  if (writeApiEnv) {
    writeFileSync(apiEnv, apiEnvContent);
    p.log.success("Created apps/api/.env");
  } else {
    p.log.warn("Skipped apps/api/.env update");
  }
  console.log("");

  // Create docker/supabase/.env
  p.log.step("Creating docker/supabase/.env");
  console.log("");
  const writeSupabaseEnv = await p.confirm({
    message: "Update docker/supabase/.env?",
    initialValue: true,
  });
  if (p.isCancel(writeSupabaseEnv)) return;

  const supabaseEnvContent = `# Database Configuration
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=postgres

# JWT Configuration
JWT_SECRET=${jwtSecret}
JWT_EXPIRY=3600

# Supabase Configuration
SUPABASE_URL=http://localhost:8000
SUPABASE_KONG_URL=http://kong:8000
API_EXTERNAL_URL=http://localhost:8000
SITE_URL=http://localhost:3000
ADDITIONAL_REDIRECT_URLS=milo://spotify/callback
DISABLE_SIGNUP=false

# Supabase Keys
SUPABASE_ANON_KEY=${anonKey}
SUPABASE_SERVICE_ROLE_KEY=${serviceRoleKey}

# GoTrue OAuth Configuration - Google (Required by docker-compose.yml)
GOTRUE_ENABLE_GOOGLE_OAUTH=true
GOTRUE_GOOGLE_CLIENT_ID=${googleClientId}
GOTRUE_GOOGLE_CLIENT_SECRET=${googleClientSecret}
GOTRUE_GOOGLE_REDIRECT_URI=http://localhost:8000/auth/v1/callback
GOTRUE_GOOGLE_SKIP_NONCE_CHECK=true

# OAuth Configuration - Apple (Legacy format)
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# GoTrue OAuth Configuration - Apple (Required by docker-compose.yml)
GOTRUE_EXTERNAL_APPLE_ENABLED=false
GOTRUE_EXTERNAL_APPLE_CLIENT_ID=
GOTRUE_EXTERNAL_APPLE_SECRET=

# OAuth Configuration - Spotify
ENABLE_SPOTIFY_OAUTH=true
SPOTIFY_CLIENT_ID=${spotifyClientId}
SPOTIFY_CLIENT_SECRET=${spotifyClientSecret}
SPOTIFY_REDIRECT_URI=milo://spotify/callback

GMAIL_REDIRECT_URI=http://localhost:8080/api/v1/integrations/gmail/callback

# Email Configuration
ENABLE_EMAIL_SIGNUP=true
ENABLE_EMAIL_AUTOCONFIRM=true

# Phone Configuration
ENABLE_PHONE_SIGNUP=false
ENABLE_PHONE_AUTOCONFIRM=false

# SMTP Configuration
SMTP_ADMIN_EMAIL=admin@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=dummy
SMTP_PASS=dummy
SMTP_SENDER_NAME=Supabase

# Mailer URL paths
MAILER_URLPATHS_INVITE=/auth/v1/verify
MAILER_URLPATHS_CONFIRMATION=/auth/v1/verify
MAILER_URLPATHS_RECOVERY=/auth/v1/verify
MAILER_URLPATHS_EMAIL_CHANGE=/auth/v1/verify

# PostgREST Configuration
PGRST_DB_SCHEMAS=public,storage,graphql_public

# Image Proxy
IMGPROXY_ENABLE_WEBP_DETECTION=true

# Kong Configuration
KONG_HTTP_PORT=8000
KONG_HTTPS_PORT=8443

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true

# Studio Configuration
STUDIO_DEFAULT_ORGANIZATION=Default Organization
STUDIO_DEFAULT_PROJECT=Default Project
DASHBOARD_USERNAME=supabase
DASHBOARD_PASSWORD=supabase

# Analytics
LOGFLARE_PUBLIC_ACCESS_TOKEN=${logflarePublicToken}
LOGFLARE_PRIVATE_ACCESS_TOKEN=${logflarePrivateToken}
LOGFLARE_API_KEY=${logflarePrivateToken}

# Functions
FUNCTIONS_VERIFY_JWT=true

# Docker
DOCKER_SOCKET_LOCATION=/var/run/docker.sock
`;

  if (writeSupabaseEnv) {
    writeFileSync(supabaseEnv, supabaseEnvContent);
    p.log.success("Created docker/supabase/.env");
  } else {
    p.log.warn("Skipped docker/supabase/.env update");
  }
  console.log("");

  // iOS Configuration
  p.log.step("iOS Configuration");
  if (existsSync(iosConfig)) {
    p.log.info("iOS Config.xcconfig found");
    let currentSupabaseUrl = "";
    const iosContent = readFileSync(iosConfig, "utf-8");
    const match = iosContent.match(/^SUPABASE_URL\s*=\s*(.+)$/m);
    if (match?.[1]) {
      currentSupabaseUrl = match[1]
        .replace("http:/\\$()/", "")
        .replace("https:/\\$()/", "");
    }

    const iosSupabaseInput = (await p.text({
      message: "Enter SUPABASE_URL for iOS app",
      initialValue: currentSupabaseUrl || "localhost:8000",
      placeholder: "localhost:8000",
    })) as string;

    if (!p.isCancel(iosSupabaseInput)) {
      let protocol = "http";
      let supabaseHost = iosSupabaseInput;
      if (
        iosSupabaseInput.includes(".loca.lt") ||
        iosSupabaseInput.includes(".ngrok") ||
        iosSupabaseInput.includes(".tunn.dev") ||
        iosSupabaseInput.startsWith("https://")
      ) {
        protocol = "https";
        supabaseHost = iosSupabaseInput.replace(/^https:\/\//, "");
      } else {
        supabaseHost = iosSupabaseInput.replace(/^http:\/\//, "");
      }

      const formattedUrl = `${protocol}:/\\$()/${supabaseHost}`;
      let updatedIosContent = iosContent;

      if (/^SUPABASE_URL\s*=/m.test(updatedIosContent)) {
        updatedIosContent = updatedIosContent.replace(
          /^SUPABASE_URL\s*=.*$/m,
          `SUPABASE_URL = ${formattedUrl}`,
        );
      } else {
        updatedIosContent += `\nSUPABASE_URL = ${formattedUrl}`;
      }

      if (/^SUPABASE_ANON_KEY\s*=/m.test(updatedIosContent)) {
        updatedIosContent = updatedIosContent.replace(
          /^SUPABASE_ANON_KEY\s*=.*$/m,
          `SUPABASE_ANON_KEY = ${anonKey}`,
        );
      } else {
        updatedIosContent += `\nSUPABASE_ANON_KEY = ${anonKey}`;
      }

      writeFileSync(iosConfig, updatedIosContent);
      p.log.success("Updated iOS Config.xcconfig");
    } else {
      p.log.warn("Skipped iOS config update");
    }
  } else {
    p.log.warn("iOS Config.xcconfig not found - skipping");
  }
  console.log("");

  // Docker Management
  p.log.step("Docker Management");
  const dockerDir = join(projectRoot, "docker");
  let hasRunningContainers = false;
  try {
    const psOutput = execSync("docker compose ps -q", {
      cwd: dockerDir,
      stdio: "pipe",
      encoding: "utf-8",
    });
    hasRunningContainers = psOutput.trim().length > 0;
  } catch {
    hasRunningContainers = false;
  }

  if (hasRunningContainers) {
    p.log.info("Docker containers running - restart required");
    const restart = await p.confirm({
      message: "Docker containers running - restart required. Restart now?",
      initialValue: true,
    });
    if (!p.isCancel(restart) && restart) {
      const spinner = p.spinner();
      spinner.start("Pulling latest images...");
      try {
        execSync("docker compose pull", { cwd: dockerDir, stdio: "inherit" });
      } catch {
        spinner.message("Some images may have failed to pull");
      }
      spinner.message("Stopping containers...");
      execSync("docker compose down", { cwd: dockerDir, stdio: "inherit" });
      spinner.message("Starting containers...");
      execSync("docker compose up -d", { cwd: dockerDir, stdio: "inherit" });
      spinner.stop("Containers restarted");
      p.log.success("Containers restarted");
    } else {
      p.log.warn("Docker restart skipped");
    }
  } else {
    const startNow = await p.confirm({
      message: "Start Docker containers now?",
      initialValue: true,
    });
    if (!p.isCancel(startNow) && startNow) {
      const spinner = p.spinner();
      spinner.start("Pulling images (this may take a few minutes)...");
      try {
        execSync("docker compose pull", { cwd: dockerDir, stdio: "inherit" });
      } catch {
        spinner.message("Some images may have failed to pull");
      }
      spinner.message("Starting containers...");
      execSync("docker compose up -d", { cwd: dockerDir, stdio: "inherit" });
      spinner.stop("Containers started");
      p.log.success("Containers started");
    } else {
      p.log.warn("Docker start skipped");
    }
  }
  console.log("");

  const totalDuration = Date.now() - setupStartedAt;
  p.outro(chalk.green(`Setup complete in ${Math.round(totalDuration / 1000)}s`));

  p.note(
    [
      "Files synced:",
      "  - docker/.env",
      "  - docker/supabase/.env",
      "  - apps/api/.env",
      "",
      "Synced values:",
      "  JWT Secret:        [SYNCED]",
      "  ANON Key:          [SYNCED]",
      "  SERVICE_ROLE Key:  [SYNCED]",
      "  Google OAuth:      [SYNCED]",
      "  Spotify OAuth:     [SYNCED]",
    ].join("\n"),
    chalk.green("Configuration Complete"),
  );
  p.note(
    [
      "Next steps:",
      "  1. Update iOS config: apps/milo/Config.xcconfig",
      "  2. Run startup: modal-cli startup",
      "     Or: cd apps/cli && bun run src/index.ts startup",
    ].join("\n"),
    "Next Steps",
  );
}
