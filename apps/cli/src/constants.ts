import chalk from "chalk";

export const APP_NAME = "modal-cli";
export const PACKAGE_NAME = "@modal/cli";
export const VERSION = "0.1.0";
export const APP_DESCRIPTION =
  "Minimal TUI for exploring and running Modal scripts";
export const DEFAULT_SCRIPTS_DIR =
  "/Users/enkyuan/Desktop/Projects/modal/scripts";

export const LOGO_LINES = [
  "███╗   ███╗ ██████╗ ██████╗  █████╗ ██╗     ",
  "████╗ ████║██╔═══██╗██╔══██╗██╔══██╗██║     ",
  "██╔████╔██║██║   ██║██║  ██║███████║██║     ",
  "██║╚██╔╝██║██║   ██║██║  ██║██╔══██║██║     ",
  "██║ ╚═╝ ██║╚██████╔╝██████╔╝██║  ██║███████╗",
  "╚═╝     ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝",
];

export const PRIMARY_COLOR = "#6B9FFF";
export const SECONDARY_COLOR = "#888888";
export const MUTED_COLOR = "#4C4C4C";
export const ACCENT_COLOR = "#3F86F4";
export const SUCCESS_COLOR = "#4ADE80";
export const ERROR_COLOR = "#F87171";

export const MENU_FOOTER =
  "↑/↓ navigate  •  enter execute  •  space preview  •  q quit  •  ? help";
export const HELP_HINT =
  "Type `modal-cli --help` for flags or press ? inside the TUI.";

export function renderLogo(subtitle: string): string {
  const title = chalk.hex(PRIMARY_COLOR).bold("modal scripts");
  const subtitleLine = chalk.hex(SECONDARY_COLOR)(subtitle);
  const art = LOGO_LINES.map((line) => chalk.hex(PRIMARY_COLOR)(line)).join(
    "\n",
  );
  return `${art}\n\n${title}\n${subtitleLine}\n`;
}

export const SETUP_SUBTITLE = "Environment Setup & Configuration";
export const STARTUP_SUBTITLE = "Application Startup & Management";
