import * as p from "@clack/prompts";
import chalk from "chalk";
import { execSync, spawn } from "child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderLogo, STARTUP_SUBTITLE } from "../constants";

function getProjectRoot(): string {
  // CLI is in apps/cli, so go up two levels to project root
  const cliDir = import.meta.dir ?? dirname(fileURLToPath(import.meta.url));
  return join(cliDir, "..", "..", "..", "..");
}

function isContainerRunning(containerName: string): boolean {
  try {
    const output = execSync(
      `docker ps --format '{{.Names}}' | grep -q "^${containerName}$" || echo ""`,
      { encoding: "utf-8", stdio: "pipe" },
    );
    return output.trim() !== "";
  } catch {
    return false;
  }
}

function waitForService(serviceName: string): Promise<boolean> {
  return new Promise((resolve) => {
    const maxAttempts = 30;
    let attempt = 1;

    const checkHealth = () => {
      try {
        const status = execSync(
          `docker inspect --format='{{.State.Health.Status}}' ${serviceName} 2>/dev/null || echo ""`,
          { encoding: "utf-8", stdio: "pipe" },
        );
        if (status.trim() === "healthy") {
          resolve(true);
          return;
        }
      } catch {
        // Service might not have healthcheck
      }

      if (attempt >= maxAttempts) {
        resolve(false);
        return;
      }

      attempt++;
      setTimeout(checkHealth, 2000);
    };

    checkHealth();
  });
}

async function startAllServices() {
  const projectRoot = getProjectRoot();
  const dockerDir = join(projectRoot, "docker");
  const dockerEnvPath = join(dockerDir, ".env");

  if (!existsSync(dockerEnvPath)) {
    p.log.warn("docker/.env not found.");
    p.log.message(`Expected at: ${dockerEnvPath}`);
    p.log.message(`Current working dir: ${process.cwd()}`);
    p.log.info("Run setup from the CLI to configure your environment:");
    p.log.message("  cd apps/cli && bun run src/index.ts setup");
    const confirmed = await p.confirm({
      message: "Continue anyway?",
      initialValue: false,
    });
    if (!confirmed || p.isCancel(confirmed)) {
      return;
    }
  }

  const spinner = p.spinner();
  spinner.start("Stopping and removing existing containers...");

  try {
    execSync("docker compose down", { cwd: dockerDir, stdio: "pipe" });
  } catch {
    // Ignore errors
  }

  spinner.message("Pulling Docker images (this may take several minutes)...");
  try {
    execSync("docker compose pull", { cwd: dockerDir, stdio: "inherit" });
    spinner.message("Images pulled successfully");
  } catch {
    spinner.message(
      "Some images failed to pull, will try to use cached versions",
    );
  }

  spinner.message("Building API container...");
  try {
    execSync("docker compose build api", { cwd: dockerDir, stdio: "inherit" });
    spinner.message("API built successfully");
  } catch {
    spinner.message(
      "API build failed, continuing with existing image if available",
    );
  }

  spinner.message("Starting all services...");
  execSync("docker compose up -d", { cwd: dockerDir, stdio: "inherit" });

  spinner.stop("All services starting...");
  p.log.info("Services may take 30-60 seconds to become healthy.");

  spinner.start("Waiting for critical services to be healthy...");
  const dbHealthy = await waitForService("supabase-db");
  if (dbHealthy) {
    spinner.message("Database is healthy");
  } else {
    spinner.message("Database may still be starting up");
  }

  const redisHealthy = await waitForService("redis");
  if (redisHealthy) {
    spinner.message("Redis is healthy");
  } else {
    spinner.message("Redis may still be starting up");
  }

  spinner.stop("Core services are healthy");

  p.note(
    [
      "API:       http://localhost:8080",
      "Supabase:  http://localhost:8000",
      "Database:  localhost:5432",
      "Redis:     redis:6379",
      "",
      "Tip: Use option 4 to configure tunnel for remote access",
    ].join("\n"),
    chalk.green("Services Started"),
  );
}

async function buildIosApp() {
  const projectRoot = getProjectRoot();
  const iosDir = join(projectRoot, "apps", "milo");

  if (!existsSync(join(iosDir, "milo.xcodeproj"))) {
    p.log.error("iOS project not found");
    return;
  }

  // List simulators
  p.log.info("Available iOS Simulators:");
  try {
    const output = execSync("xcrun simctl list devices available", {
      encoding: "utf-8",
    });
    const devices = output
      .split("\n")
      .filter((line) => line.includes("iPhone") || line.includes("iPad"))
      .filter((line) => !line.includes("unavailable"))
      .slice(0, 10);
    devices.forEach((device, index) => {
      console.log(`  ${index + 1}. ${device.trim()}`);
    });
  } catch {
    p.log.warn("Could not list simulators");
  }

  const deviceInput = await p.text({
    message: "Enter simulator number (or press Enter for default)",
    placeholder: "1",
  });

  if (p.isCancel(deviceInput)) {
    return;
  }

  const spinner = p.spinner();
  spinner.start("Booting simulator...");

  // Get booted device or default
  let selectedUdid: string = "";
  try {
    const booted = execSync(
      "xcrun simctl list devices | grep Booted | head -n 1",
      {
        encoding: "utf-8",
      },
    );
    if (booted.trim()) {
      const match = booted.match(/\(([A-Z0-9-]+)\)/);
      if (match) {
        selectedUdid = match[1];
      }
    }
  } catch {
    // Fallback to iPhone 15 Pro
    try {
      const output = execSync(
        'xcrun simctl list devices | grep "iPhone 15 Pro" | grep -v Max | head -n 1',
        { encoding: "utf-8" },
      );
      const match = output.match(/\(([A-Z0-9-]+)\)/);
      if (match) {
        selectedUdid = match[1];
      }
    } catch {
      // Could not find default
    }
  }

  if (!selectedUdid) {
    spinner.stop("Could not find simulator");
    return;
  }

  try {
    execSync(`xcrun simctl boot ${selectedUdid}`, { stdio: "pipe" });
  } catch {
    // Already booted
  }

  execSync("open -a Simulator", { stdio: "pipe" });

  spinner.message("Building app...");
  try {
    execSync(
      `xcodebuild -project milo.xcodeproj -scheme milo -sdk iphonesimulator -destination "id=${selectedUdid}" -configuration Debug -derivedDataPath ./build clean build`,
      { cwd: iosDir, stdio: "inherit" },
    );
    spinner.message("Build successful");
  } catch {
    spinner.stop("Build failed");
    return;
  }

  spinner.message("Installing app on simulator...");
  const appPath = join(
    iosDir,
    "build",
    "Build",
    "Products",
    "Debug-iphonesimulator",
    "milo.app",
  );

  if (!existsSync(appPath)) {
    spinner.stop("App bundle not found");
    return;
  }

  try {
    execSync(`xcrun simctl install ${selectedUdid} "${appPath}"`, {
      stdio: "inherit",
    });
    spinner.message("App installed");
  } catch {
    spinner.stop("Installation failed");
    return;
  }

  spinner.message("Launching app...");
  try {
    execSync(`xcrun simctl launch ${selectedUdid} com.tangram.labs.milo`, {
      stdio: "inherit",
    });
    spinner.stop("App launched successfully");
  } catch {
    spinner.stop("Launch failed");
  }
}

async function checkStatus() {
  const projectRoot = getProjectRoot();
  const dockerDir = join(projectRoot, "docker");

  p.log.info("Service Status:");
  try {
    execSync("docker compose ps", { cwd: dockerDir, stdio: "inherit" });
  } catch {
    p.log.error("Could not check service status");
  }
}

async function stopServices() {
  const choice = await p.select({
    message: "Select shutdown option",
    options: [
      { value: "stop", label: "Stop containers (keep data)" },
      { value: "down", label: "Remove containers (keep volumes/data)" },
      {
        value: "down-v",
        label: "Remove containers and volumes (⚠️  deletes all data)",
      },
      {
        value: "full",
        label: "Full cleanup (⚠️  deletes everything including images)",
      },
      { value: "cancel", label: "Cancel" },
    ],
  });

  if (p.isCancel(choice) || choice === "cancel") {
    return;
  }

  const projectRoot = getProjectRoot();
  const dockerDir = join(projectRoot, "docker");

  const spinner = p.spinner();

  if (choice === "stop") {
    spinner.start("Stopping Docker containers...");
    execSync("docker compose stop", { cwd: dockerDir, stdio: "inherit" });
    spinner.stop("Containers stopped");
  } else if (choice === "down") {
    spinner.start("Removing Docker containers...");
    execSync("docker compose down", { cwd: dockerDir, stdio: "inherit" });
    spinner.stop("Containers removed");
  } else if (choice === "down-v") {
    const confirmed = await p.confirm({
      message:
        "⚠️  WARNING: This will delete all database data, Redis data, etc. Are you sure?",
      initialValue: false,
    });
    if (confirmed && !p.isCancel(confirmed)) {
      spinner.start("Removing Docker containers and volumes...");
      execSync("docker compose down -v", { cwd: dockerDir, stdio: "inherit" });
      spinner.stop("Containers and volumes removed");
    }
  } else if (choice === "full") {
    const confirmed = await p.confirm({
      message:
        "⚠️  WARNING: This will delete EVERYTHING (containers, volumes, and images). Are you sure?",
      initialValue: false,
    });
    if (confirmed && !p.isCancel(confirmed)) {
      spinner.start("Removing Docker containers, volumes, and images...");
      execSync("docker compose down -v --rmi all", {
        cwd: dockerDir,
        stdio: "inherit",
      });
      spinner.stop("Full cleanup complete");
    }
  }
}

async function viewLogs() {
  const choice = await p.select({
    message: "Select logs to view",
    options: [
      { value: "api", label: "Modal API logs" },
      { value: "auth", label: "Supabase Auth logs" },
      { value: "db", label: "Database logs" },
      { value: "redis", label: "Redis logs" },
      { value: "all", label: "All logs" },
    ],
  });

  if (p.isCancel(choice)) {
    return;
  }

  const projectRoot = getProjectRoot();
  const dockerDir = join(projectRoot, "docker");

  const service = choice === "all" ? "" : choice;
  const child = spawn(
    "docker",
    ["compose", "logs", "-f", service].filter(Boolean),
    {
      cwd: dockerDir,
      stdio: "inherit",
    },
  );

  p.log.info("Press Ctrl+C to stop streaming logs.");

  await new Promise<void>((resolve) => {
    const handleSigint = () => {
      child.kill("SIGINT");
    };

    process.once("SIGINT", handleSigint);

    const cleanup = () => {
      process.removeListener("SIGINT", handleSigint);
      resolve();
    };

    child.on("close", cleanup);
    child.on("exit", cleanup);
    child.on("error", cleanup);
  });
}

function validateUrl(url: string): boolean {
  // Check if URL matches common patterns (http/https with domain)
  const urlPattern =
    /^https?:\/\/[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/;
  return urlPattern.test(url);
}

function updateEnvFile(filePath: string, updates: Record<string, string>) {
  if (!existsSync(filePath)) {
    return;
  }

  let content = readFileSync(filePath, "utf-8");
  for (const [key, value] of Object.entries(updates)) {
    const regex = new RegExp(`^${key}=.*$`, "m");
    if (regex.test(content)) {
      content = content.replace(regex, `${key}=${value}`);
    } else {
      content += `\n${key}=${value}`;
    }
  }
  writeFileSync(filePath, content);
}

async function configureTunnel() {
  p.log.step("Tunnel Configuration");
  p.log.info("This will update all URLs to use your tunnel for remote access.");
  p.log.info("Configuration modes:");
  p.log.message("  localhost - For simulator or same machine testing");
  p.log.message("  tunnel    - For physical device testing (remote access)");
  p.log.info(
    "Note: If using a single tunnel for both ports, enter the same URL twice.",
  );
  p.log.info(
    "Or enter 'localhost' for either to use local mode for that service.",
  );

  const supabaseInput = await p.text({
    message: "Enter tunnel URL for Supabase (port 8000)",
    placeholder: "https://your-tunnel.tunn.dev OR localhost",
  });

  if (p.isCancel(supabaseInput) || !supabaseInput) {
    p.log.error("No URL provided");
    return;
  }

  const apiInput = await p.text({
    message: "Enter tunnel URL for API (port 8080)",
    placeholder: "https://your-tunnel.tunn.dev OR localhost",
  });

  if (p.isCancel(apiInput) || !apiInput) {
    p.log.error("No URL provided");
    return;
  }

  // Process Supabase URL
  let supabaseUrl: string;
  let supabaseProtocol: string;
  let supabaseHost: string;

  if (supabaseInput === "localhost" || supabaseInput === "local") {
    supabaseUrl = "http://localhost:8000";
    supabaseProtocol = "http";
    supabaseHost = "localhost:8000";
  } else {
    if (!validateUrl(supabaseInput)) {
      p.log.error("Invalid Supabase URL format");
      p.log.info("Expected format: https://your-domain.com");
      return;
    }

    supabaseUrl = supabaseInput.replace(/\/$/, "");
    supabaseProtocol = supabaseUrl.startsWith("https://") ? "https" : "http";
    supabaseHost = supabaseUrl.replace(/^https?:\/\//, "");
  }

  // Process API URL
  let apiUrl: string;
  let apiProtocol: string;
  let apiHost: string;
  let wsProtocol: string;

  if (apiInput === "localhost" || apiInput === "local") {
    apiUrl = "http://localhost:8080";
    apiProtocol = "http";
    apiHost = "localhost:8080";
    wsProtocol = "ws";
  } else {
    if (!validateUrl(apiInput)) {
      p.log.error("Invalid API URL format");
      p.log.info("Expected format: https://your-domain.com");
      return;
    }

    apiUrl = apiInput.replace(/\/$/, "");
    apiProtocol = apiUrl.startsWith("https://") ? "https" : "http";
    apiHost = apiUrl.replace(/^https?:\/\//, "");
    wsProtocol = apiProtocol === "https" ? "wss" : "ws";
  }

  // Show summary
  p.note(
    [
      `Supabase (port 8000):`,
      `  URL:           ${supabaseUrl}`,
      `  OAuth Redirect: ${supabaseUrl}/auth/v1/callback`,
      ``,
      `API (port 8080):`,
      `  URL:           ${apiUrl}/api/v1`,
      `  WebSocket:     ${wsProtocol}://${apiHost}/api/v1`,
      `  Gmail Redirect: ${apiUrl}/api/v1/integrations/gmail/callback`,
    ].join("\n"),
    "Configuration Summary",
  );

  const confirmed = await p.confirm({
    message: "Update configuration files with these URLs?",
    initialValue: false,
  });

  if (p.isCancel(confirmed) || !confirmed) {
    p.log.info("Cancelled");
    return;
  }

  const projectRoot = getProjectRoot();
  const dockerEnv = join(projectRoot, "docker", ".env");
  const supabaseEnv = join(projectRoot, "docker", "supabase", ".env");
  const apiEnv = join(projectRoot, "apps", "api", ".env");
  const iosConfig = join(projectRoot, "apps", "milo", "Config.xcconfig");

  const spinner = p.spinner();

  // Update docker/.env
  spinner.start("Updating docker/.env...");
  updateEnvFile(dockerEnv, {
    SUPABASE_URL: supabaseUrl,
    SUPABASE_PUBLIC_URL: supabaseUrl,
    API_EXTERNAL_URL: supabaseUrl,
    GOOGLE_REDIRECT_URI: `${supabaseUrl}/auth/v1/callback`,
    GMAIL_REDIRECT_URI: `${apiUrl}/api/v1/integrations/gmail/callback`,
  });
  spinner.stop("Updated docker/.env");

  // Update docker/supabase/.env
  spinner.start("Updating docker/supabase/.env...");
  updateEnvFile(supabaseEnv, {
    SUPABASE_URL: supabaseUrl,
    API_EXTERNAL_URL: supabaseUrl,
    GOTRUE_GOOGLE_REDIRECT_URI: `${supabaseUrl}/auth/v1/callback`,
    GMAIL_REDIRECT_URI: `${apiUrl}/api/v1/integrations/gmail/callback`,
  });
  spinner.stop("Updated docker/supabase/.env");

  // Update apps/api/.env
  spinner.start("Updating apps/api/.env...");
  updateEnvFile(apiEnv, {
    SUPABASE_KONG_URL: supabaseUrl,
  });
  spinner.stop("Updated apps/api/.env");

  // Update iOS Config.xcconfig
  if (existsSync(iosConfig)) {
    spinner.start("Updating iOS Config.xcconfig...");
    let iosContent = readFileSync(iosConfig, "utf-8");
    const formattedSupabase = `${supabaseProtocol}:/${"$()"}/${supabaseHost}`;
    const formattedApi = `${apiProtocol}:/${"$()"}/${apiHost}`;
    const formattedWs = `${wsProtocol}:/${"$()"}/${apiHost}`;

    iosContent = iosContent.replace(
      /^API_BASE_URL = .*$/m,
      `API_BASE_URL = ${formattedApi}/api/v1`,
    );
    iosContent = iosContent.replace(
      /^WEBSOCKET_URL = .*$/m,
      `WEBSOCKET_URL = ${formattedWs}/api/v1`,
    );
    iosContent = iosContent.replace(
      /^SUPABASE_URL = .*$/m,
      `SUPABASE_URL = ${formattedSupabase}`,
    );

    writeFileSync(iosConfig, iosContent);
    spinner.stop("Updated Config.xcconfig");
  }

  p.log.success("All configuration files updated");

  // Show reminders
  const needsReminders =
    (supabaseInput !== "localhost" && supabaseInput !== "local") ||
    (apiInput !== "localhost" && apiInput !== "local");

  if (needsReminders) {
    const reminders: string[] = [];
    if (supabaseInput !== "localhost" && supabaseInput !== "local") {
      reminders.push(
        `1. Update Google OAuth redirect URIs in Google Cloud Console: ${supabaseUrl}/auth/v1/callback`,
      );
      reminders.push(
        "3. Ensure your tunnel is running and forwarding port 8000",
      );
    }
    reminders.push(
      "2. Restart Docker containers for changes to take effect: cd docker && docker compose restart",
    );
    if (apiInput !== "localhost" && apiInput !== "local") {
      reminders.push(
        "4. Ensure your tunnel is running and forwarding port 8080",
      );
    }

    p.note(reminders.join("\n"), chalk.yellow("⚠️  Important Reminders"));
  } else {
    p.log.info("Note: Restart Docker containers for changes to take effect");
    p.log.info("     cd docker && docker compose restart");
  }
}

export async function startupCommand() {
  console.log(renderLogo(STARTUP_SUBTITLE));
  p.intro(chalk.bgBlue.black(" Modal Application Startup "));

  while (true) {
    const choice = await p.select({
      message: "Startup Options",
      options: [
        { value: "1", label: "Start Docker containers only" },
        { value: "2", label: "Start Docker + Build and run iOS app" },
        { value: "3", label: "Build and run iOS app only" },
        { value: "4", label: "Configure tunnel/port forwarding" },
        { value: "5", label: "Stop/cleanup services" },
        { value: "6", label: "Check service status" },
        { value: "7", label: "View logs" },
        { value: "0", label: "Exit" },
      ],
    });

    if (p.isCancel(choice) || choice === "0") {
      p.outro(chalk.green("Goodbye!"));
      break;
    }

    switch (choice) {
      case "1":
        await startAllServices();
        break;
      case "2":
        await startAllServices();
        await new Promise((resolve) => setTimeout(resolve, 5000));
        await buildIosApp();
        break;
      case "3":
        await buildIosApp();
        break;
      case "4":
        await configureTunnel();
        break;
      case "5":
        await stopServices();
        break;
      case "6":
        await checkStatus();
        break;
      case "7":
        await viewLogs();
        break;
    }

    // Add a pause before showing menu again (except for exit and logs)
    if (choice && choice !== "7") {
      // Don't pause for logs (option 7) as user can Ctrl+C to exit
      const continueInput = await p.text({
        message: "Press Enter to continue...",
        placeholder: "",
      });
      if (p.isCancel(continueInput)) {
        return;
      }
    }
  }
}
