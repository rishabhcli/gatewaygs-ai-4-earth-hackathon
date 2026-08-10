import type { ReactElement } from "react";

import { useSystemState } from "./useSystemState";

function OrbitalMark(): ReactElement {
  return (
    <svg aria-hidden="true" className="orbital-mark" viewBox="0 0 160 160" role="img">
      <circle cx="80" cy="80" r="44" />
      <ellipse cx="80" cy="80" rx="72" ry="25" />
      <path d="M31 30 129 130" />
      <circle className="orbital-point" cx="128" cy="62" r="5" />
    </svg>
  );
}

function StatePanel(): ReactElement {
  const state = useSystemState();
  const operational = state.phase === "ready";
  const dependencyChecks =
    state.phase === "ready" || state.phase === "degraded" ? state.health.checks : [];

  return (
    <section className="state-panel" aria-labelledby="state-title">
      <div className="panel-heading">
        <p className="eyebrow">Live development boundary</p>
        <p
          className={`signal signal--${operational ? "ready" : state.phase}`}
          role="status"
          aria-live="polite"
        >
          <span aria-hidden="true" />
          {state.phase === "loading" && "Checking dependencies"}
          {state.phase === "ready" && "Foundation services ready"}
          {state.phase === "degraded" && "Dependency unavailable"}
          {state.phase === "offline" && "Control plane unreachable"}
        </p>
      </div>

      <h2 id="state-title">Readiness is not evidence.</h2>
      <p className="state-explanation">
        These checks prove only that the local control plane can reach its real
        persistence boundaries. They do not claim a methane retrieval, model, flux
        estimate, deployment, or production use.
      </p>

      <dl className="state-grid">
        <div>
          <dt>Product state</dt>
          <dd>Not yet in production</dd>
        </div>
        <div>
          <dt>Analysis intake</dt>
          <dd>Refused until the pipeline exists</dd>
        </div>
        <div>
          <dt>Result claims</dt>
          <dd>None published</dd>
        </div>
      </dl>

      {dependencyChecks.length > 0 ? (
        <ul className="checks" aria-label="Dependency checks">
          {dependencyChecks.map((check) => (
            <li key={check.name}>
              <span>{check.name}</span>
              <strong data-status={check.status}>{check.code}</strong>
            </li>
          ))}
        </ul>
      ) : null}

      {state.phase === "offline" ? (
        <p className="refusal" role="alert">
          <strong>{state.code}</strong>
          No cached status is shown as current. Start the repository-owned services and
          re-run the semantic health check.
        </p>
      ) : null}
    </section>
  );
}

export function App(): ReactElement {
  return (
    <div className="page-shell">
      <header className="masthead">
        <div className="identity">
          <span className="identity-index">S2 / SWIR</span>
          <span>Methane evidence system</span>
        </div>
        <p className="production-label">System state 00 · not yet in production</p>
      </header>

      <main id="main-content">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="kicker">A reproducibility instrument</p>
            <h1 id="hero-title">
              Evidence begins
              <br />
              with <em>refusal.</em>
            </h1>
            <p className="lede">
              The system will turn Sentinel-2 L1C shortwave-infrared scenes into plume
              candidates and uncertainty-aware flux intervals. Until each invariant is
              defended, it says exactly what it cannot support.
            </p>
          </div>
          <div className="hero-instrument">
            <OrbitalMark />
            <p>
              <span>Target signal</span>
              B12 methane absorption
            </p>
            <p>
              <span>Reference</span>
              Same geometry + orbit
            </p>
          </div>
        </section>

        <StatePanel />

        <section className="method-strip" aria-label="Required evidence chain">
          <p>Required evidence chain</p>
          <ol>
            <li>L1C scene</li>
            <li>Empirical null</li>
            <li>Morphology mask</li>
            <li>Wind + interval</li>
            <li>Visible limits</li>
          </ol>
        </section>
      </main>

      <footer>
        <p>Free satellite data. Reproducible processing. Explicit abstention.</p>
        <p>GatewayGS &amp; The AEI Initiative: AI 4 Earth Hackathon</p>
      </footer>
    </div>
  );
}
