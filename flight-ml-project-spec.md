# Flight Price Prediction & Anomaly Detection System
### "Google Flights on Steroids" — Project Spec

## Overview
An AI/ML-powered flight search and prediction system that goes beyond standard flight search by forecasting price movement, quantifying prediction uncertainty, detecting anomalous/error fares, and continuously retraining itself on live data.

**Core story for resume/interviews:** A production-grade ML system that doesn't just show flight prices, but predicts where they're going, how confident it is, and flags when something looks statistically wrong — deployed, monitored, and self-improving.

---

## Feature List (Prioritized)

### Core ML — Build These First
- [ ] **Price prediction with backtested accuracy metric** — `9/10`
  - Gradient boosting model (XGBoost/LightGBM) predicting price direction/magnitude
  - Features: days-until-departure, day-of-week, route popularity, historical volatility, holidays
  - Validate against real historical data; report a concrete accuracy number (e.g., "73% accuracy, 2-week horizon")
- [ ] **Uncertainty-quantified forecasting** — `8/10`
  - Quantile regression or Monte Carlo dropout instead of a single point prediction
  - Output: "70% chance price drops below $X in next 5 days"
- [ ] **Explainability (SHAP values)** — `7/10`
  - Show which features drove each individual prediction
  - Cheap to add on top of the base model, high interview payoff

### Advanced / Differentiating ML
- [ ] **Anomaly / error-fare detection** — `8/10`
  - Statistical outlier detection (not just a threshold) flagging fares priced well below model expectation
  - Security-adjacent framing: outlier/adversarial pricing detection
- [ ] **Route-network graph model (GNN)** — `7/10`
  - Model airports/routes as a graph; predict price propagation across the network
  - High effort/risk — only pursue if time allows after core is solid
- [ ] **Causal inference on price drivers** — `6/10`
  - Simple causal forest to estimate causal (not just correlated) effect of features
  - Risky to defend under close questioning — validate carefully before including

### Systems / Engineering Depth
- [ ] **Full MLOps loop** — `8/10`
  - Automatic retraining as new price data arrives
  - Live dashboard tracking model accuracy over time
- [ ] **Real deployment with caching/indexing** — `7/10`
  - Sub-second search across multi-airport/flexible-date space
- [ ] **Account/auth system** — `6/10`
  - Reasonable engineering signal; not core to the ML story but fine to include
- [ ] **CI/CD + test coverage** — `6/10`
  - Makes the repo look professionally engineered when reviewed

### Demo / "Wow Factor"
- [ ] **Live animated backtest replay** — `8/10`
  - Predicted vs. actual price curves animating over historical data — best single demo moment
- [ ] **Natural-language query parsing** — `6/10`
  - e.g. "cheapest weekend trip under $300" → structured search params

### Explicitly Out of Scope
- Full booking/checkout flow — `2/10` (pure plumbing, no ML/systems signal)

---

## Recommended Build Order
1. Data pipeline — daily price snapshots across a fixed set of routes (Skyscanner/Amadeus/Kiwi API)
2. Core price prediction model + backtested accuracy metric
3. Uncertainty quantification layer
4. Anomaly/error-fare detector
5. MLOps loop (retraining + accuracy dashboard)
6. Deployment + caching/indexing
7. Demo layer: animated backtest replay
8. Polish: SHAP explainability, NL query parsing, auth, CI/CD

**Core recommended combo for resume narrative:**
Price prediction + uncertainty quantification + anomaly detection + MLOps loop, with the animated backtest as the demo centerpiece.

---

## Tech Stack Notes
- **Data source:** Skyscanner / Amadeus / Kiwi flight search APIs (free tier)
- **Modeling:** XGBoost/LightGBM (primary), quantile regression for uncertainty, SHAP for explainability
- **Backend:** deployed API (not localhost-only) with caching layer
- **Frontend:** minimal — this is a backend/ML project, not a UI showcase
- **MLOps:** scheduled retraining job + accuracy-tracking dashboard

## Key Principle
Every architectural decision must be explainable cold in an interview — why gradient boosting over a neural net, what the uncertainty bands actually represent, why anomaly detection uses the method it does. Build only what you can defend under follow-up questioning.
