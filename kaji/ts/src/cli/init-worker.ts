/** Internal process boundary used by `kaji init` to pin its target directory. */
import { runInitWorkerMain, scaffoldRecoveryDirectory } from "@/cli/init";

runInitWorkerMain()
  .then(() => {
    process.stdout.write('{"ok":true}\n');
  })
  .catch((error: unknown) => {
    const recovery = scaffoldRecoveryDirectory(error);
    if (recovery !== undefined) {
      process.stdout.write(`${JSON.stringify({ ok: false, recovery })}\n`);
    }
    process.exitCode = 1;
  });
