// Runs Vitest from the canonical spelling of the project path. Arguments are passed through.
//
// On Windows a shell can report the drive letter in lower case ("c:\..."). Vitest then
// loads itself under one spelling of the path and the test files under the other, ending
// up with two instances, and every test file fails with "Vitest failed to find the runner".
// realpath.native returns the canonical spelling ("C:\..."); starting Vitest from it avoids
// the split. On other platforms this is a plain pass-through.

import { spawnSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = realpathSync.native(join(dirname(fileURLToPath(import.meta.url)), '..'));
const vitest = join(root, 'node_modules', 'vitest', 'vitest.mjs');

const { status, error } = spawnSync(process.execPath, [vitest, ...process.argv.slice(2)], {
  cwd: root,
  stdio: 'inherit',
});
if (error) throw error;
process.exit(status ?? 1);
