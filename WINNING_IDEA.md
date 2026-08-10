# GatewayGS & The AEI Initiative: AI 4 Earth Hackathon: Winning Idea Dossier

> **Status:** Idea selected; no product name assigned; no implementation started.
> **Submission deadline:** August 15, 2026 at 2:00 PM PT.
> **Ground truth:** [HACKATHON.md](./HACKATHON.md) remains authoritative for rules, form fields, eligibility, and links.

## Final decision

A free Sentinel-2 methane-plume retrieval and flux-estimation pipeline whose learned morphology model removes scene-specific false plumes.

## Why this document exists

This is the recovered and finalized output of the Claude Opus 5 Max brainstorming session, including its ruthless elimination, rubric scoring, adversarial review, committed scope, technical architecture, early kill test, build order, demo plan, and honest failure modes. Descriptive phrases below are concept labels only, not a project name.

## Pass 1 — Kill

2. cloud-corrected-alert-statistics — Undemoable. The winning moment is two lines on a chart whose divergence a judge cannot evaluate without trusting a latent-class model they will not read.

3. water-cannot-be-created — Rubric miss. Scores 9 on technical thoughtfulness and 3 on everything a video can convey; the likely honest result is "conserved but slightly worse," which is a losing sentence at a hackathon.

4. red-team-the-verifier — Out of scope. To show the evasive clearing you must synthesize imagery of a clearing that doesn't exist, which is a second research project bolted onto the first.

5. slick-to-ship — Out of scope. Needs a real slick, in a SAR scene, with matched free AIS, in the same 6 days; the joint probability of finding that triple by Wednesday is well under half, and the failure mode is silent until Thursday.

6. what-actually-turned-on — Already exists. WattTime sells exactly this, and the visible artifact is a regression coefficient — a judge sees a chart, not software.

7. plants-that-report-nothing — Already exists. Climate TRACE published this; worse, the demo's payload is a curve over an unverifiable plant, so the "wow" is asserted rather than shown.

8. the-unmetered-acre — Out of scope. OpenET account approval and district extraction records are both latency risks you cannot control, and the plausible outcome is an interval that contains the reported number.

9. did-the-park-work — Rubric miss, and this is my error, not a close call: matched DiD is statistics, not AI. The spec says "use AI as a core component (not just a superficial add-on)" and a judge asking "where's the model?" has no good answer. Three of my twelve share this defect.

10. fires-that-cannot-shrink — Slop. I flagged it myself and then kept it anyway; wildfire prediction is the most common serious climate hackathon submission and you'd be competing on execution inside a frame five other people also chose.

Survivors: 1, 11, 12.

## Pass 2 — Score the survivors

Verbatim axes, each /10. Note that "Your videos will be judged" makes video legibility a stated criterion, not a soft one.

1. sentinel-2-as-a-gas-camera

		
Problem clearly identified	9	Unmonitored methane super-emitters; specific, dated, locatable.
AI as core, not add-on	7	Real only if the learned detector is load-bearing; the retrieval itself is physics.
Technical thoughtfulness / creativity	10	Repurposing a crop-monitoring satellite as a gas camera is the surprising part.
Contribution to the environment	9	Methane is the highest-leverage near-term forcing; detection is directly actionable.
Software's technical ability	9	Spectral retrieval + synthetic data generation + segmentation + flux inversion.
Video legibility	10	Invisible → visible in one cut, no setup required.
Total	54	

11. the-error-bar-on-a-credit

		
Problem clearly identified	9	Offset integrity, topical and sharp.
AI as core	7	Learned biomass model, but the interesting work is statistical.
Thoughtfulness / creativity	8	Strong idea, low visual surprise.
Environment	7	Indirect and negative-framed — it corrects a market rather than fixing a thing.
Technical ability	9	Weighted, spatially blocked conformal is genuinely hard.
Video legibility	5	The payload is an error bar. Landing it requires teaching coverage on camera.
Total	45	

12. the-map-of-what-we-dont-know

		
Problem clearly identified	8	Exposure inequity, concrete.
AI as core	6	Hierarchical GP; a student judge may not read it as AI at all.
Thoughtfulness / creativity	7	Good twist inside a crowded domain.
Environment	8	Strongest justice narrative of the three.
Technical ability	7	Real but modest, and it degrades gracefully into kriging, which is the danger.
Video legibility	9	Two maps. Anyone gets it instantly.
Total	45	

Tie for second at 45. Broken toward 12, because videos are the explicitly named judging medium and 11 loses five points exactly there.

## Pass 3 — Adversarial review
### Against sentinel-2-as-a-gas-camera

"This isn't AI. You did band arithmetic on two channels and called it machine learning. The physics was published in 2021 by people with an atmospheric science PhD; you reimplemented their equation. Also — you picked a desert. Show me a landfill outside Chicago. You can't, can you? So this works over the emptiest 15% of the planet, on plumes so large somebody already noticed them, which is why you were able to validate against a published number. You found things that were already found."

Concede, partly. The scope objection is correct and I mis-scoped this in my first pass — I wrote "landfill or well pad" and that was wrong. The B11/B12 method needs bright, spectrally homogeneous, low-vegetation surfaces and has a detection floor around 1–3 t/hr. Vegetated temperate landfills are largely out. You must say this in the video before a judge says it to you; getting caught overclaiming coverage is worse than the limited coverage.

Answer the rest. The "not AI" charge is the one that decides the project, and it is answerable by construction: the physics gets you a noisy scalar field, and that field is full of false plumes from soil moisture and mineral variation that look identical to methane in exactly the channel you're using. No threshold separates them, because the discriminating information is morphology, not magnitude. Learning that morphology from synthetically injected plumes over real artifact backgrounds is the actual solution, it is not decorative, and the false-positive rate before-and-after is a number you can put on screen. Build it so that if you deleted the network the system stops working, and the objection dies.

The "already found" charge is weaker than it sounds: reproducing published fluxes is validation, not the product. The product is that the pipeline runs on any coordinate, on free imagery, back to 2015.

### Against the-map-of-what-we-dont-know

"You made two maps. The first is a smoothing of data I could have plotted in a spreadsheet, and the second is the standard deviation of the first, which any Gaussian process gives you for free — it's a property of where you put the sensors, not a discovery. Then you overlaid income data and asked me to be moved. The finding is 'poor neighborhoods have fewer air sensors,' which is not a finding. Where is the software? Where is the model doing anything I couldn't get from scikit-learn's gp.predict(return_std=True)?"

Largely concede. This is the fatal one and I do not have a full answer. The variance surface is substantially a function of sensor geometry, so the headline result is partly baked in before any modeling. The only thing that rescues it is the partially identified low-cost-sensor bias term — variance that inflates because the calibration is unsupported there, not just because the sensors are sparse — and that distinction requires a paragraph to explain, which violates your own Step 5. Under time pressure you will retreat to kriging plus a fixed correction, and then it is a colored map.

## Pass 4 — Commit

Idea 1. sentinel-2-as-a-gas-camera.

## The one-line version

"It finds methane leaks using the free farm-monitoring satellite — I point it at a coordinate and a date, and it shows you an invisible gas plume and tells you how many tonnes an hour are coming out."

## The specific problem

Methane traps roughly 80× more heat than CO₂ over twenty years, and a small number of point sources — well pads, compressor stations, blowouts, pipeline venting — account for a disproportionate share of oil and gas emissions. Who has the problem: regulators and mitigation NGOs who need evidence a leak occurred, and operators whose own leak detection runs on scheduled ground surveys and aerial flyovers costing thousands per site visit, typically once or twice a year. What it costs: a single uncontrolled well blowout can release tens of thousands of tonnes before anyone stops it, and the gap between "started leaking" and "someone noticed" is routinely weeks to months. The dedicated methane satellites are commercially targeted or narrow-swath. Sentinel-2 has been imaging the entire planet every five days since 2015, for free, in two shortwave-infrared bands that happen to straddle a methane absorption feature — and almost nobody uses it this way.

## Scope boundary

The one thing it does: given a coordinate and a date, return methane plume detections over that scene with a flux estimate and an uncertainty interval.

Explicitly not building:

Scheduled or global scanning. No monitoring service, no cron, no alerting. One AOI, one date, on demand.
Operator or facility attribution. No joins against well databases, no naming companies. The output is a plume and a number, not a defendant.
Any second sensor. No TROPOMI, no Landsat, no EMIT, no PRISMA fusion. Multi-sensor is the most seductive Day 4 idea and it will eat the whole day and produce nothing on screen.
## Architecture
coordinate + date
   ↓
Copernicus Data Space  →  S2 L1C granules (NOT L2A — atmospheric
                          correction removes the signal you want)
   ↓
reference-date selection  →  N cloud-free prior acquisitions, same tile
                             + same relative orbit, ranked by spectral
                             distance in B11
   ↓
MBMP retrieval            →  ΔR field  ← HARD PART LIVES HERE
   ↓
ΔR → ΔΩ conversion        →  methane column enhancement, via Beer-Lambert
                             LUT over the B12 spectral response, corrected
                             for solar + viewing airmass
   ↓
U-Net segmentation        →  plume mask   ← AND HERE
   ↓
IME flux inversion        →  Q = U_eff · IME / L, U_eff from ERA5 10m wind
   ↓
overlay PNG + t/hr + interval

The hard part lives in two places and nowhere else: the confound structure of ΔR, and the sim-to-real gap in the detector's training data. Everything upstream is I/O and everything downstream is arithmetic.

## The hard technical core

Methane absorbs in Sentinel-2's B12 (~2190 nm) and essentially not in B11 (~1610 nm). So the ratio

ΔR = (R12 / R12_ref) / (R11 / R11_ref) − 1

should cancel everything that affects both bands equally and leave only methane. It does not. B11 and B12 respond differently to soil moisture, clay and carbonate mineralogy, vegetation water content, and sun/view geometry. Any surface change between your reference date and your target date leaves a residual in precisely the channel you are reading as gas. Over bright homogeneous sand this residual is small. Over anything else it dominates, and it produces coherent blobs that look exactly like plumes.

This means three things, and they are the project:

The threshold cannot be a constant. It has to come from the empirical null distribution of ΔR over the clean pixels of that specific scene, because the noise floor is scene-dependent — it is set by that terrain's spectral heterogeneity, not by the sensor.

The discriminating signal is shape, not magnitude. A real plume is connected, elongated, anchored at one end at a point source, and oriented within roughly ±30° of the ERA5 wind vector, with a monotonic decay along the axis. A soil-moisture artifact is none of those things reliably. That is a learnable morphological prior and it is why a network beats a threshold.

You can generate unlimited labeled training data. Take real ΔR fields from dates with no known emission over the same tiles — those are your artifact backgrounds, for free, with correct statistics. Simulate plumes (Gaussian plume model is adequate; randomize flux, wind speed, direction, source location, stability class), push them through the same ΔR→ΔΩ LUT in reverse, and inject. Train a small U-Net on the composite. Hold out every real event entirely. The failure mode is sim-to-real: if your synthetic plumes are too smooth, the net learns "smooth blob," and real turbulent plumes with broken filaments get missed. Counter with per-sample turbulent perturbation of the concentration field and heavy domain randomization over background albedo.

The second calibration risk: converting ΔR into a column enhancement requires the band-averaged methane absorption over B12's spectral response at the relevant two-way airmass. Get that constant wrong by 30% and every flux you report is wrong by 30% in a way nothing in your pipeline will reveal. Anchor it by reproducing a published event's reported flux, then keep it fixed.

Flux itself is the integrated mass enhancement method: sum ΔΩ over the mask, multiply by pixel area and molar mass, then Q = U_eff · IME / L with L = √(plume area) and U_eff from a published linear relation to ERA5 U10. Wind speed error will dominate your uncertainty budget, not retrieval noise — say so in the video, it reads as competence.

## Build order

Front-loaded so a demoable artifact exists by end of Day 1 and everything after is improvement.

### Day 0 (today) — access, 4–6 hours. Copernicus Data Space account. Pull one L1C granule over a documented super-emitter event, read B11 and B12 as arrays, confirm 20 m geometry. Source your anchor events from Varon et al. 2021 (Hi-res methane emissions from Sentinel-2), Irakulis-Loitxate et al. on Turkmenistan and Algeria, and the UNEP IMEO MARS database — pull exact dates and coordinates from those directly, don't trust anyone's recall including mine. Gate: if L1C is not in memory by tonight, the project is dead. Pivot now, not Wednesday.

### Day 1 — retrieval, ugly and end-to-end. MBSP and MBMP on one known large event. Look at the ΔR image. Gate: if a published, well-documented, very large plume does not appear by end of Day 1, stop and switch to idea 12. By tonight you should have a script taking lat/lon/date and emitting a ΔR PNG. That script alone is a submittable demo.

### Day 2 — flux and external validation. Build the ΔR→ΔΩ LUT, IME, ERA5 wind, U_eff. Compare your flux to the published flux for that event; tune the constant; freeze it. Run 2–3 more published events. You now have a validation table, which converts every claim in your video from assertion to reproduction.

### Day 3 — synthetic data and detector. Plume simulator, ~2000 clean ΔR backgrounds from non-event dates over the same tiles, injection, small U-Net. Real events strictly held out.

### Day 4 — evaluation that survives scrutiny. Precision/recall on held-out synthetic; false-positive rate across N clean real scenes — this is the number that matters and the one you put on screen; detection of the real published events the net never trained on; threshold from the empirical null.

### Day 5 — video, screenshots, README, Devpost fields, repo hygiene. Nothing new gets built. Last six hours are submission mechanics only.

### Day 6 morning — buffer, then submit by 10:00 AM PT against a 2:00 PM deadline. Do not test the deadline.

## Riskiest assumption

That MBMP on free Sentinel-2 will visibly resolve a plume, on a scene you chose, within one day of work.

Cheapest test, hours 6–14: one published blowout-scale event, not a marginal leak. Pull L1C for the event date plus three prior dates. Compute R12/R12_ref, then the B11-corrected version. Look at the image. Total cost: an afternoon.

Run the null immediately after: the same computation on a date with no known emission over the same tile. If a convincing "plume" appears there too, your artifacts dominate — which is survivable, because it means the morphological detector is the project rather than an enhancement, and you should reallocate Day 2 into Day 3. If nothing appears on the real event, you learn that at hour 14 instead of hour 100.

## The demo — shot by shot (~2:30)
0:00–0:12 — Plain Sentinel-2 RGB of the site. "This is a free public satellite image from [date]. There is a large gas leak in this frame. You can't see it, because methane is invisible."
0:12–0:25 — Hard cut, same frame, plume overlay resolves, flux counter runs up to the number. ← WINNING MOMENT AT 0:18. No narration over it. Let it sit.
0:25–0:50 — Why it works: one diagram, methane's absorption spectrum with B11 and B12 marked. Twenty seconds, no more.
0:50–1:20 — The honesty beat, and the reason you win rather than place: run the identical math on a clean scene and show the false plume that soil moisture produces. "This is why a threshold doesn't work."
1:20–1:50 — The AI, positioned as the fix for the thing you just showed: synthetic plumes injected into real backgrounds, U-Net trained, false-positive rate drops from A to B on screen as two numerals.
1:50–2:15 — Validation table: your flux vs. published flux, three events, none seen during training.
2:15–2:30 — Scale: every five days, globally, free, archive back to 2015. One sentence on what that enables. Stop.
## Rubric map
"Clearly identify an environmental problem" — methane super-emitters emitting for weeks before detection; named, dated, coordinate-located events.
"Use AI as a core component, not a superficial add-on" — the physics produces an ambiguous field; the learned morphological detector is what makes it usable, and the before/after false-positive number proves it isn't decoration.
"Technical thoughtfulness, creativity" — a crop-monitoring satellite used as a gas camera, with a scene-adaptive null-derived threshold instead of a magic constant.
"Potential positive impact on the planet" / "contribution to the environment" — highest-leverage near-term climate forcing, and the output is directly actionable by a repair crew.
"Your software's technical ability" — retrieval, radiative calibration, synthetic data generation, segmentation, flux inversion, uncertainty propagation, in one pipeline.
"Your videos will be judged" — the winning moment lands at 0:18 with zero setup.
## What would make this lose anyway

The coverage limitation, if a judge finds it before you tell them. This works over bright, homogeneous, low-vegetation terrain at fluxes above roughly 1–3 t/hr. That is a real fraction of global oil and gas infrastructure and a poor fit for temperate landfills. Say it out loud in the video. Being caught overclaiming is fatal; disclosing a limitation reads as rigor.

A judge concluding the AI is bolted onto physics. This is the live risk and it is decided entirely by whether the false-positive section at 0:50–1:50 lands. If you cut that section for time, you lose.

Losing to polish. At a hackathon this size, a competitor may submit a full-stack app with a login, a map, and a chatbot, and student judges may score legible product completeness over depth. You cannot control that. The only counter is that your two and a half minutes are shot, cut, and paced better than anyone else's — which is worth spending Day 5 on, and is the reason Day 5 builds nothing.
