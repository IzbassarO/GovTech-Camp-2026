# GovTech Camp Selection Stage — Research Report (Condensed, EN)

**Competition context.** GovTech Camp selection stage (main partner: inDrive). ~40 teams, only ~15–20 advance to the main 10-week program. Deadline: 23:59, July 17, 2026 (GMT+5). Deliverables: GitHub repo + README, demo video, 7–10 slides. Local Docker Compose demo is sufficient. Scoring (100 pts): Problem 15, Value 15, Data 15, **AI/ML 20**, Explainability 10, Prototype 15, UX/demo 5, Docs 5. Mandatory: human-in-the-loop, explainable outputs, real open or documented synthetic data. Forbidden: repeating the team's Decentrathon 5.0 case (AgroScore subsidy scoring), black-box AI, "portal for everything".

**Strategic frame.** Startup in partnership with government (B2G / B2B2G). Benchmark: the **Sergek operator model** — a private partner invests (~53B KZT) and the state pays for results/operation (total contract 93.2B KZT through 2030, 22,000 cameras, payment only after commissioning). Goal: position the team's future TOO (LLC) as a long-term operator — data pipeline, model retraining, monitoring, SLA.

---

## Ranked Top-6 Ideas

### #1 — Aqtal: medical claims anti-fraud operator for OSMS/GOBMP — ~92/100
- **Problem (2026 headlines):** MinFin IT audit of the Social Health Insurance Fund (FSMS, transferred to MinFin on Jan 16, 2026): 3,640 services billed to deceased patients; 769,446 gender-mismatched screenings worth 1.8B KZT (768,827 men "passed" cervical-cancer screening). Supreme Audit Chamber: 34.3B KZT potential losses (~28B outpatient upcoding + 4.1B double financing). AFM: 26B KZT of fictitious services in 2025. Fund budget 2026: 2.4T KZT.
- **User & model:** FSMS monitoring auditor + clinic compliance teams (dual market). Subscription + success fee (% of prevented/recovered payouts) — a healthcare payment-integrity operator.
- **Data:** fully synthetic claims dataset with documented, seeded anomalies from real audit findings, calibrated to open FSMS regional statistics. No PII, no API-token dependency.
- **AI stack:** rules engine (impossible cases: sex/age/date-of-death) → Isolation Forest / autoencoder anomaly detection → bipartite graph clinic↔doctor↔patient (phantom-activity clusters) → LLM agent generating a human-readable case dossier.
- **Explainability:** violated rule citation + SHAP factor breakdown + LLM dossier per flag.
- **HITL:** system only ranks cases; auditor confirms/rejects/requests info; payments are never auto-blocked.
- **5-day MVP:** FastAPI + Postgres, synthetic generator, rules + IF + SHAP, networkx graph, LLM dossiers, Next.js dashboard, Docker Compose. Cut first: graph module.
- **Demo wow:** load a month of claims → top-20 suspicious cases worth X M KZT in seconds → "male cervical screening" case + phantom-patient clinic graph + auto-generated dossier.
- **Risks:** synthetic data may look toy-like (mitigate with methodology + calibration); sensitive topic (offset: the state itself is building pre-payment anti-fraud filters); topic-collision risk: medium-low.

### #2 — Adal Satu 2.0: procurement intelligence for auditors + business — ~91/100
- **Problem:** collusion and supplier-tailored tenders; the new procurement law No. 106-VIII (in force Jan 1, 2025) bans affiliated bidders in one lot, but affiliation checks are not automated. SK-Pharmacia case: alleged 35.8B KZT damage; drug prices 40–365% above market.
- **User & model:** SaaS for state auditors (MinFin / Supreme Audit / anticorruption) + counterparty-check and "win honestly" analytics for businesses (dual market).
- **Data:** goszakup OCDS API **requires a MinFin token (verified: HTTP 401 without it)**. Fallbacks: data.egov.kz dumps, GitHub/GitLab OCDS samples, Statsnet Relations API, adata.kz (5 free checks/day), DFO.kz affiliated-persons registry.
- **AI stack:** XGBoost + SHAP lot risk scoring; customer–supplier–founder graph (community detection / GNN) for collusion rings; LLM reads tender specs and flags supplier-tailored requirements. Cut first: GNN → community detection.
- **Risks:** no ground-truth collusion labels (weak supervision, disclose honestly); token timing unknown; **high topic-collision risk** (obvious theme); politically sensitive.

### #3 — Jylu: heat-network failure prediction + repair prioritization — ~87/100
- **Problem:** Ekibastuz 2022 accident (~130 buildings cut off in −30°C; city ~150k people); Ekibastuz network wear 92.1% over 342.3 km; 12 cities with critical wear >65%; national modernization program >13.5T KZT (2025–2029; targets: wear → 40%, accidents −20%).
- **AI:** survival/GBM failure probability per pipe segment + budget-constrained repair optimization ("accidents prevented per tenge"); SHAP + risk map; the engineer approves the plan.
- **Data:** synthetic segments calibrated to real network lengths + open weather data. Cut first: optimizer → plain risk ranking.
- **Risks:** no real sensor data; low collision risk. **Best backup** if fraud themes get crowded.

### #4 — Su Qalqan: flood decision-support layer over Tasqyn — ~86/100
- **Problem:** 2024 floods — worst in ~80 years, >300B KZT recovery, 116,949 evacuated (40,781 children). GloFAS warned in 2024, but there was "no interface to process the data in time"; Tasqyn (2025, 142 hydroposts) still lacks local decision support.
- **AI:** Sentinel-2 water segmentation (before/after) + level forecasting + population exposure via DEM + LLM briefing for the duty officer. Cut first: CNN → NDWI thresholding.
- **Risks:** satellite CV in 5 days is ambitious; low-medium collision.

### #5 — Otkel: border throughput & inspection-targeting risk engine — ~84/100
- **Problem:** autumn 2025 — 7,000–10,000 trucks stuck at Kazakhstan's borders, waits up to 7 days; Dostyk/Alashankou capacity ~1,000 vehicles/day; truck downtime ~25k RUB/day.
- **AI:** declaration risk scoring (whom to inspect without slowing everyone) + queue/transit-time forecasting per crossing. Dual market: customs + logistics companies; strong inDrive mobility DNA.
- **Risks:** border data closed → heavy reliance on synthetic; low collision.

### #6 — Quat Control: electricity commercial-loss / theft detection — ~82/100
- **Problem:** power-line wear >70% (up to 80% regionally); commercial losses reach ~20% of supply in some grids; 2025 deficit up to 5.7B kWh.
- **AI:** autoencoder anomalies on consumption profiles + feeder imbalance → ranked raid list with SHAP. Cut first: autoencoder → Isolation Forest.
- **Risks:** narrow B2G market; low collision.

---

## Final Recommendation — Build Aqtal (#1)

Why it beats Adal Satu under the startup frame: (1) cleaner 5-day data story — documented synthetic data, no token dependency (goszakup confirmed HTTP 401 without a token); (2) perfect operator business model — FSMS moved under MinFin on Jan 16, 2026 and is itself building pre-payment anti-fraud filters, so a private operator walks through an open door with state endorsement; (3) lower topic-collision risk than procurement; (4) comparable AI breadth; (5) headline-grade problem numbers.

**Switch triggers:** MinFin token arrives fast AND ≥3–4 teams take the medical theme → switch to Adal Satu. Many teams take procurement → stay on Aqtal. Both fraud themes crowded → fall back to Jylu.

## 5-Day Build Plan (July 12–17)
- **Jul 12:** lock the choice; design synthetic schema + anomaly list from audit findings; FastAPI + Postgres + Docker skeleton; request the goszakup token (insurance for #2).
- **Jul 13:** seedable synthetic generator (documented anomaly shares, calibrated to FSMS regional stats); rules module + baseline.
- **Jul 14:** Isolation Forest + SHAP; case risk score; unit tests on planted anomalies.
- **Jul 15:** bipartite graph + communities; LLM case-dossier agent; wire into the API.
- **Jul 16:** Next.js dashboard (flag queue, case card, auditor decision buttons); record demo video; README.
- **Jul 17:** one-command Docker run polish; 8 slides; push to GitHub; submit before 23:59 (keep a bug buffer).

## 8-Slide Deck (mapped to the rubric)
1. Problem + numbers (34.3B KZT losses; 996 deceased "patients"; 768,827 male cervical screenings) → Problem 15
2. Solution & operator business model (who pays, success fee, dual market) → Value 15
3. Data: synthetic methodology + calibration to open statistics → Data 15
4. AI architecture (rules + anomaly + graph + LLM) and why plain automation fails → AI/ML 20
5. Explainability: rule → SHAP → LLM dossier, one case shown in all three layers → Explainability 10
6. Human-in-the-loop & ethics (AI never blocks; auditor decides — matches inDrive's human-centric stance)
7. Prototype + demo (architecture, Docker, metrics on synthetic ground truth) → Prototype 15 + UX 5
8. TOO-operator roadmap (pilot with FSMS, SLA) + team credentials (1st place, Meta Llama Accelerator) → Docs 5

## Score-Maximizing Tactics
1. Ensemble of paradigms (rules + unsupervised anomaly + graph + LLM) — breadth wins the heaviest criterion.
2. Report precision/recall/PR-AUC on planted ground-truth anomalies — rare at hackathons, signals maturity.
3. Layered explainability demonstrated on one concrete case.
4. Counterfactuals: "remove this factor → risk drops 0.93 → 0.40".
5. Visible HITL UX: confirm/reject buttons + a decision log.

## Caveats
- Synthetic data is double-edged: legally clean and fully controlled, but can feel "toy" — mitigate with a documented generation methodology, calibration to open FSMS statistics, and a note that the architecture accepts real de-identified feeds.
- Unverified: whether GovTech Camp customers will provide anonymized FSMS data, and the official 2026 customer task list (if it already includes anti-fraud/procurement, priorities shift).
- goszakup token issuance timing is unknown (HTTP 401 confirmed without a token) — Adal Satu must be built on fallbacks.
- One more narrow research iteration is worthwhile only on two questions: (1) the official GovTech Camp 2026 customer task list; (2) participant access to anonymized FSMS data.
