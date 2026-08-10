import { lstat, mkdir, rm } from "node:fs/promises";
import path from "node:path";

import {
  chromium,
  expect,
  test as base,
  type BrowserContext,
  type Page,
} from "@playwright/test";

interface TestFixtures {
  page: Page;
}

interface WorkerFixtures {
  persistentContext: BrowserContext;
}

async function requireRealDirectory(directory: string, label: string): Promise<void> {
  const metadata = await lstat(directory);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error(`${label} must be a real directory`);
  }
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
  persistentContext: [
    async ({ browserName }, runFixture, workerInfo) => {
      if (browserName !== "chromium") {
        throw new Error("persistent E2E profile supports only the Chromium project");
      }
      const repositoryRoot = path.resolve(process.cwd(), "../..");
      const developmentRoot = path.join(repositoryRoot, ".dev");
      const profileRoot = path.join(developmentRoot, "pw-profile");
      await requireRealDirectory(developmentRoot, "development state");
      await mkdir(profileRoot, { mode: 0o700, recursive: true });
      await requireRealDirectory(profileRoot, "Playwright profile root");

      const workerProfile = path.join(
        profileRoot,
        `worker-${String(workerInfo.workerIndex)}`,
      );
      await rm(workerProfile, { force: true, recursive: true });
      await mkdir(workerProfile, { mode: 0o700 });

      const context = await chromium.launchPersistentContext(workerProfile, {
        baseURL: "http://127.0.0.1:4171",
        headless: true,
      });
      try {
        await runFixture(context);
      } finally {
        await context.close();
      }
    },
    { scope: "worker" },
  ],
  page: async ({ persistentContext }, runFixture) => {
    const page = await persistentContext.newPage();
    try {
      await runFixture(page);
    } finally {
      await page.close();
    }
  },
});

export { expect };
