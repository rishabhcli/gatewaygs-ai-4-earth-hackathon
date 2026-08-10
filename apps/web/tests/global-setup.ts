import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default async function requireSemanticDevelopmentHealth(): Promise<void> {
  const repositoryRoot = path.resolve(process.cwd(), "../..");
  const python = path.join(repositoryRoot, ".venv", "bin", "python");
  const devctl = path.join(repositoryRoot, "scripts", "devctl.py");
  const result = await execFileAsync(python, [devctl, "health"], {
    cwd: repositoryRoot,
    encoding: "utf8",
    maxBuffer: 64 * 1024,
    timeout: 60_000,
  });
  if (!result.stdout.includes("HEALTH OK;")) {
    throw new Error("dev:health did not emit its semantic readiness contract");
  }
}
