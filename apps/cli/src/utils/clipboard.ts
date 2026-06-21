import { spawnSync } from "node:child_process";

export function copyToClipboard(text: string): boolean {
  const tries: { cmd: string; args: string[] }[] =
    process.platform === "darwin"
      ? [{ cmd: "pbcopy", args: [] }]
      : process.platform === "win32"
        ? [{ cmd: "clip", args: [] }]
        : [
            { cmd: "xclip", args: ["-selection", "clipboard"] },
            { cmd: "wl-copy", args: [] },
          ];
  for (const t of tries) {
    const r = spawnSync(t.cmd, t.args, { input: text });
    if (r.status === 0) return true;
  }
  return false;
}
