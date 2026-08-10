import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { healthResponse, productState } from "./contracts.ts";

void describe("runtime contracts", () => {
  void it("accepts the explicit not-yet-in-production state", () => {
    assert.deepEqual(
      productState.parse({
        contract_version: "1",
        production_state: "not-yet-in-production",
        analysis_jobs_supported: false,
        reason_code: "PIPELINE_NOT_IMPLEMENTED",
      }),
      {
        contract_version: "1",
        production_state: "not-yet-in-production",
        analysis_jobs_supported: false,
        reason_code: "PIPELINE_NOT_IMPLEMENTED",
      },
    );
  });

  void it("rejects a fabricated supported-job state", () => {
    assert.throws(() =>
      productState.parse({
        contract_version: "1",
        production_state: "not-yet-in-production",
        analysis_jobs_supported: true,
        reason_code: "PIPELINE_NOT_IMPLEMENTED",
      }),
    );
  });

  void it("rejects an unknown health contract version", () => {
    assert.throws(() =>
      healthResponse.parse({
        contract_version: "2",
        service: "api",
        status: "ready",
        checks: [],
      }),
    );
  });

  void it("accepts bounded dependency checks", () => {
    assert.equal(
      healthResponse.parse({
        contract_version: "1",
        service: "api",
        status: "ready",
        checks: [{ name: "postgis", status: "pass", code: "POSTGIS_QUERY_OK" }],
      }).status,
      "ready",
    );
  });

  void it("rejects unknown fields at every contract boundary", () => {
    assert.throws(() =>
      productState.parse({
        contract_version: "1",
        production_state: "not-yet-in-production",
        analysis_jobs_supported: false,
        reason_code: "PIPELINE_NOT_IMPLEMENTED",
        fabricated: true,
      }),
    );
    assert.throws(() =>
      healthResponse.parse({
        contract_version: "1",
        service: "api",
        status: "ready",
        checks: [
          {
            name: "postgis",
            status: "pass",
            code: "POSTGIS_QUERY_OK",
            fabricated: true,
          },
        ],
      }),
    );
  });
});
