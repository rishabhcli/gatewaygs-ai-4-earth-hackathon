import { z } from "zod";

const dependencyCheck = z
  .object({
    name: z.string().min(1),
    status: z.enum(["pass", "fail"]),
    code: z.string().min(1),
  })
  .strict();

export const healthResponse = z
  .object({
    contract_version: z.literal("1"),
    service: z.literal("api"),
    status: z.enum(["alive", "ready", "not-ready"]),
    checks: z.array(dependencyCheck).max(16),
  })
  .strict();

export const productState = z
  .object({
    contract_version: z.literal("1"),
    production_state: z.literal("not-yet-in-production"),
    analysis_jobs_supported: z.literal(false),
    reason_code: z.literal("PIPELINE_NOT_IMPLEMENTED"),
  })
  .strict();

export type HealthResponse = z.infer<typeof healthResponse>;
export type ProductState = z.infer<typeof productState>;
