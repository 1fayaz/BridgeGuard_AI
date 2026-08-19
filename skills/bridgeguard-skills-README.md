# BridgeGuard AI — Skills README

> A skills.sh skill collection for AI-powered IoT bridge & infrastructure monitoring.
> Covers the full pipeline: **sensor ingestion → data refinement → mathematical analysis → visual output → PDF reports.**

---

## 📦 Skill Collection Overview

```
bridgeguard-skills/
├── iot-sensor-ingestion/        # Ingest & parse raw sensor data
│   └── SKILL.md
├── data-refinement/             # Clean, filter, normalize sensor streams
│   └── SKILL.md
├── sensor-comparison/           # Compare readings across sensors & time
│   └── SKILL.md
├── structural-research/         # Research bridge specs & failure benchmarks
│   └── SKILL.md
├── math-analysis/               # FFT, statistics, fatigue & risk calculations
│   └── SKILL.md
├── visual-output/               # Charts, heatmaps, dashboard-ready visuals
│   └── SKILL.md
└── pdf-report/                  # Auto-generate bridge health PDF reports
    └── SKILL.md
```

---

## 🔧 Installation

Install the full BridgeGuard skill suite using the skills.sh CLI:

```bash
# Install all BridgeGuard skills at once
npx skills add bridgeguard/skills/iot-sensor-ingestion
npx skills add bridgeguard/skills/data-refinement
npx skills add bridgeguard/skills/sensor-comparison
npx skills add bridgeguard/skills/structural-research
npx skills add bridgeguard/skills/math-analysis
npx skills add bridgeguard/skills/visual-output
npx skills add bridgeguard/skills/pdf-report
```

Or install individually based on what your pipeline needs.

---

## 🗂️ Skill Definitions

---

### 1. `iot-sensor-ingestion`

```yaml
---
name: iot-sensor-ingestion
description: >
  Use this skill to ingest, parse, and validate raw IoT sensor data from bridge
  monitoring hardware. Triggers when the user provides CSV, JSON, MQTT payloads,
  or serial data from sensors including accelerometers, vibration sensors, strain
  gauges, crack detection sensors, load cells, and temperature probes. Handles
  missing fields, timestamp alignment, and unit normalization before passing data
  downstream.
---
```

**What it does:**
- Accepts sensor data in CSV, JSON, MQTT, or REST API format
- Maps raw byte payloads to human-readable field names
- Validates sensor IDs, timestamps, and unit types
- Flags null readings, sensor dropouts, and out-of-range spikes
- Outputs a clean, structured dataset ready for refinement

**Supported Sensor Types:**

| Sensor | Measures | Unit |
|---|---|---|
| Accelerometer | Vibration / movement | m/s² |
| Strain Gauge | Structural deformation | microstrain (με) |
| Crack Sensor | Crack width over time | mm |
| Load Cell | Live load on deck | kN |
| Temperature Probe | Thermal expansion | °C |
| Tiltmeter | Angular displacement | degrees |
| Displacement LVDT | Deflection under load | mm |

**Example trigger phrases:**
> "Parse this sensor CSV from our bridge"
> "I have MQTT data from 6 accelerometers on Bridge-04"
> "Load this JSON from our IoT gateway"

---

### 2. `data-refinement`

```yaml
---
name: data-refinement
description: >
  Use this skill to clean, filter, and normalize IoT sensor streams for
  bridge monitoring. Triggers when raw sensor data contains noise, outliers,
  missing values, duplicate timestamps, or unit inconsistencies. Applies
  signal processing techniques including moving averages, Butterworth filters,
  z-score outlier removal, and interpolation to produce reliable datasets
  for downstream analysis.
---
```

**What it does:**
- Removes electrical noise using low-pass Butterworth filters
- Detects and removes outliers using Z-score (threshold: ±3σ)
- Fills missing readings via linear interpolation
- Resamples data to uniform time intervals (e.g., 10Hz → 1Hz)
- Normalizes units across multi-sensor setups
- Flags permanently failed sensors vs. temporary dropout

**Refinement Pipeline:**
```
Raw Sensor Stream
      ↓
Remove Duplicates & Sort by Timestamp
      ↓
Outlier Detection (Z-score / IQR)
      ↓
Low-pass Filter (noise removal)
      ↓
Interpolate Missing Values
      ↓
Normalize Units & Resample
      ↓
Clean Dataset ✓
```

**Example trigger phrases:**
> "Clean this vibration data, it has a lot of noise"
> "Remove outliers from my strain gauge readings"
> "Normalize the sensor data before analysis"

---

### 3. `sensor-comparison`

```yaml
---
name: sensor-comparison
description: >
  Use this skill to compare sensor readings across multiple bridge locations,
  time periods, or structural zones. Triggers when the user wants to identify
  anomalies by comparing current sensor readings against historical baselines,
  compare two bridges side by side, or detect asymmetric loading patterns
  across left vs. right spans. Outputs comparison tables, delta values,
  and deviation flags.
---
```

**What it does:**
- Compares current readings against historical baseline (rolling 30/90/365 day)
- Cross-compares symmetrical sensor pairs (left span vs. right span)
- Detects progressive degradation trends over time
- Highlights sensors exceeding design thresholds
- Produces side-by-side bridge comparison reports

**Comparison Modes:**

| Mode | Use Case |
|---|---|
| **Temporal** | Today vs. last month vs. last year |
| **Spatial** | Left deck vs. right deck sensors |
| **Cross-Bridge** | Bridge A vs. Bridge B (same type) |
| **Threshold** | Reading vs. design specification limit |
| **Trend** | Rate of change over time (degradation speed) |

**Example trigger phrases:**
> "Compare this month's vibration to last year's baseline"
> "Are the left and right span sensors showing different readings?"
> "Which sensors are exceeding their design limits?"

---

### 4. `structural-research`

```yaml
---
name: structural-research
description: >
  Use this skill to research bridge structural specifications, engineering
  standards, failure benchmarks, and material fatigue thresholds relevant
  to bridge health monitoring. Triggers when the user needs to look up
  acceptable deflection limits, vibration frequency thresholds, load
  capacity standards (IRC, AASHTO, Eurocode), or historical failure case
  studies for comparison against current sensor readings.
---
```

**What it does:**
- Looks up design standards: IRC (India), AASHTO (USA), Eurocode (Europe)
- Retrieves acceptable thresholds for vibration, deflection, strain
- Searches historical failure cases matching current sensor patterns
- Identifies bridge type-specific risk factors (suspension, girder, arch)
- Maps sensor readings to known pre-failure signatures

**Key Standards Referenced:**

| Standard | Region | Covers |
|---|---|---|
| IRC:6-2017 | India | Loads on highway bridges |
| AASHTO LRFD | USA | Bridge design specifications |
| Eurocode 1 | Europe | Actions on structures |
| IS:456 | India | Concrete structure limits |
| IS:800 | India | Steel structure limits |

**Example trigger phrases:**
> "What is the acceptable deflection limit for a 40m span bridge?"
> "What vibration frequency indicates resonance risk?"
> "Find failure cases similar to our current strain readings"

---

### 5. `math-analysis`

```yaml
---
name: math-analysis
description: >
  Use this skill to perform mathematical and statistical calculations on
  bridge IoT sensor data. Triggers when the user needs FFT (frequency
  analysis), RMS vibration calculations, fatigue cycle counting, structural
  risk scoring, regression analysis, eigenfrequency identification, or
  load distribution modelling. Outputs numerical results, risk scores,
  and mathematical summaries with formulas shown.
---
```

**What it does:**
- **FFT Analysis** — converts time-domain vibration to frequency domain to detect resonance
- **RMS Calculation** — root mean square of vibration amplitude for severity scoring
- **Rainflow Counting** — fatigue cycle counting per ASTM E1049 standard
- **Risk Scoring** — weighted 0–100 score from multi-sensor inputs
- **Regression** — trend lines to predict future degradation rate
- **Modal Analysis** — identifies natural frequencies of the bridge structure
- **Load Distribution** — calculates stress distribution across deck sections

**Core Formulas Used:**

```
# RMS Vibration
RMS = √(1/N × Σ xᵢ²)

# Fatigue Damage (Miner's Rule)
D = Σ (nᵢ / Nᵢ)   → failure when D ≥ 1.0

# Risk Score (Weighted)
Risk = (w₁ × V_norm) + (w₂ × S_norm) + (w₃ × C_norm) + (w₄ × A_norm)
     where V=vibration, S=strain, C=crack, A=age factor

# Natural Frequency
f = (1/2π) × √(k/m)   → compare to measured FFT peaks

# Deflection Limit Check
δ_actual ≤ L/800  (live load)
δ_actual ≤ L/300  (dead load)
```

**Risk Score Output:**

| Score | Status | Action |
|---|---|---|
| 0 – 30 | 🟢 Safe | Routine monitoring |
| 31 – 60 | 🟡 Watch | Increased inspection frequency |
| 61 – 80 | 🟠 Warning | Engineering assessment required |
| 81 – 100 | 🔴 Critical | Immediate closure recommended |

**Example trigger phrases:**
> "Run FFT on the accelerometer data from sensor A3"
> "Calculate the fatigue damage index for this bridge"
> "What is the risk score based on today's readings?"
> "Predict when this bridge will reach critical threshold"

---

### 6. `visual-output`

```yaml
---
name: visual-output
description: >
  Use this skill to generate visual data representations from processed
  bridge IoT sensor data. Triggers when the user needs charts, graphs,
  heatmaps, time-series plots, frequency spectra, risk dashboards, or
  any other visual output from sensor readings or analysis results.
  Produces dashboard-ready React components or standalone HTML charts
  using Recharts, D3, or Plotly.
---
```

**What it does:**
- Time-series line charts for sensor readings over time
- FFT frequency spectrum plots
- Risk score gauges and progress bars
- Bridge deck heatmaps showing stress distribution
- Multi-sensor comparison bar charts
- Trend lines with degradation forecasts
- Live dashboard components (React/Recharts)
- Static chart images for PDF embedding

**Visual Output Types:**

| Visual | Data Source | Tool |
|---|---|---|
| Time-series chart | Any sensor over time | Recharts LineChart |
| FFT spectrum | Accelerometer / vibration | Plotly |
| Risk gauge | Risk score (0–100) | Recharts RadialBar |
| Deck heatmap | Strain gauge array | D3.js |
| Comparison bar chart | Multi-bridge / multi-period | Recharts BarChart |
| Trend forecast | Regression output | Recharts + trendline |
| Alert timeline | Event log | Recharts ComposedChart |

**Example trigger phrases:**
> "Show me a chart of the vibration data for the past 30 days"
> "Create a heatmap of strain across the bridge deck"
> "Build a dashboard showing all sensor risk scores"
> "Plot the FFT spectrum from sensor A3"

---

### 7. `pdf-report`

```yaml
---
name: pdf-report
description: >
  Use this skill to generate professional PDF bridge health monitoring
  reports from analyzed IoT sensor data. Triggers when the user wants
  to produce a maintenance report, inspection summary, risk assessment
  document, or government submission report. Outputs a multi-page PDF
  with cover page, executive summary, sensor data tables, embedded charts,
  mathematical analysis results, risk scores, and maintenance recommendations.
---
```

**What it does:**
- Generates multi-page PDF reports using ReportLab
- Includes cover page with bridge ID, date, and risk status
- Executive summary with plain-language risk verdict
- Sensor data tables (current vs. baseline vs. threshold)
- Embedded charts and heatmaps from visual-output skill
- Mathematical analysis section with formulas and results
- Maintenance recommendation table with priority ranking
- Appendix with raw sensor data logs
- Government-ready format (letterhead, signatures section)

**Report Structure:**

```
Page 1  — Cover Page (Bridge ID, Date, Risk Status Badge)
Page 2  — Executive Summary (plain language, 1 page)
Page 3  — Sensor Readings Summary Table
Page 4  — Time-Series Charts (last 30 days)
Page 5  — FFT Analysis & Frequency Findings
Page 6  — Risk Score Breakdown (weighted formula)
Page 7  — Comparison vs. Baseline & Standards
Page 8  — Maintenance Recommendations (prioritized)
Page 9  — Appendix: Raw Data Log
Page 10 — Sign-off & Inspector Details
```

**Example trigger phrases:**
> "Generate a bridge health report for Bridge-04"
> "Create a PDF maintenance report from today's sensor data"
> "Produce a government submission report for the municipality"
> "Export the risk analysis as a PDF"

---

## 🔄 Full Pipeline Flow

```
IoT Sensors (Hardware)
        ↓
[Skill 1] iot-sensor-ingestion
  → Parse CSV / JSON / MQTT payloads
        ↓
[Skill 2] data-refinement
  → Filter noise, remove outliers, normalize
        ↓
[Skill 3] sensor-comparison
  → Compare vs. baseline, vs. design limits
        ↓
[Skill 4] structural-research
  → Look up standards, failure benchmarks
        ↓
[Skill 5] math-analysis
  → FFT, RMS, fatigue, risk score calculation
        ↓
        ├──────────────────────┐
        ↓                      ↓
[Skill 6] visual-output    [Skill 7] pdf-report
  → Charts, heatmaps,       → Professional PDF
    dashboards                 for engineers &
                               governments
```

---

## 🛠️ Tech Stack These Skills Are Built For

| Layer | Technology |
|---|---|
| Sensor Hardware | Raspberry Pi + MPU6050 / HX711 / DS18B20 |
| Data Protocol | MQTT (Mosquitto broker) |
| Backend | Python (Flask / FastAPI) |
| Data Processing | NumPy, SciPy, Pandas |
| ML / AI | Scikit-learn, TensorFlow Lite |
| Visualization | Recharts, Plotly, D3.js |
| Frontend | React.js + Tailwind CSS |
| PDF Generation | ReportLab |
| Database | PostgreSQL + TimescaleDB |
| Deployment | Vercel (frontend) + Railway (backend) |

---

## 📋 Skill Dependency Map

```
iot-sensor-ingestion  ←── required by all other skills
data-refinement       ←── requires: iot-sensor-ingestion
sensor-comparison     ←── requires: data-refinement
structural-research   ←── standalone (can run independently)
math-analysis         ←── requires: data-refinement + structural-research
visual-output         ←── requires: math-analysis
pdf-report            ←── requires: math-analysis + visual-output
```

---

## 🚀 Quick Start for Claude Code

Once skills are installed, use Claude Code with natural language:

```bash
# In your project folder with Claude Code active:

"Ingest the sensor data from bridge_04_june2026.csv"
→ triggers: iot-sensor-ingestion

"Clean the data and remove noise"
→ triggers: data-refinement

"Run full mathematical analysis and calculate risk score"
→ triggers: math-analysis + structural-research

"Build a dashboard showing all results visually"
→ triggers: visual-output

"Generate the monthly PDF report for the municipality"
→ triggers: pdf-report
```

---

## 📄 License

MIT License — open for community contribution.
Built for the BridgeGuard AI project. Contributions welcome.

---

*Built with ❤️ to save lives through smarter infrastructure monitoring.*
