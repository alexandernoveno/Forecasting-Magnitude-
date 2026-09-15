/* Replay the verification vectors from model_bundle.json through forecast.js.
 *
 * The browser recomputes the 22 features and the model predictions in
 * JavaScript. Python already computed both. If the two ever disagree the page
 * reports wrong forecasts silently, so this asserts they agree to 1e-6.
 *
 *     node verify_bundle.cjs
 */
const fs = require("fs");
const path = require("path");
const F = require("./landing/forecast.js");

const bundle = JSON.parse(fs.readFileSync(path.join(__dirname, "landing/model_bundle.json"), "utf8"));
const catalogue = JSON.parse(fs.readFileSync(path.join(__dirname, "landing/catalogue.json"), "utf8"));
bundle.vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "verification_vectors.json"), "utf8")).vectors;

const FEAT_TOL = 1e-6;

/* Per-model prediction tolerance.
 *
 * Three of the four models are smooth functions of the feature vector, so they
 * agree to floating-point noise. A random forest is not smooth: it is a sum of
 * step functions, and a feature value that differs from Python's in the seventh
 * decimal can land on the other side of a split threshold. One flipped split in
 * one tree moves the ensemble mean by at most (leaf spread) / (number of trees),
 * about 0.7 / 300, and measurement across 60 vectors puts the worst case at
 * 2.4e-3 magnitude units, which is half a percent of the model's own RMSE.
 *
 * The forest tolerance is set just above that measured bound: loose enough to
 * accept threshold straddling, tight enough that a genuine traversal bug, which
 * would be off by tenths, still fails. */
const PRED_TOL = { random_forest: 5e-3, gradient_boosting: 1e-5, elastic_net: 1e-5, lstm: 1e-5 };

let featFail = 0, predFail = 0, checked = 0;
const worst = { feature: { name: null, diff: 0 }, model: { name: null, diff: 0 } };

bundle.vectors.forEach((vec, vi) => {
  const [lat, lon] = vec.epicentre;
  const events = vec.events.slice().sort((a, b) => b.before - a.before);
  const context = F.regionalContext(catalogue, lat, lon, vec.t_end_days, bundle);
  const raw = F.buildFeatures(events, context, bundle);

  bundle.features.forEach((name, i) => {
    checked += 1;
    const expected = vec.features[i];
    const got = raw[i];
    if (expected === null) {
      if (got !== null && isFinite(got)) { featFail += 1; console.log(`  vector ${vi} ${name}: expected null, got ${got}`); }
      return;
    }
    const diff = Math.abs(got - expected);
    const rel = diff / Math.max(1, Math.abs(expected));
    if (rel > worst.feature.diff) { worst.feature = { name: `${name} (vector ${vi})`, diff: rel }; }
    if (rel > FEAT_TOL) {
      featFail += 1;
      if (featFail <= 8) { console.log(`  FEATURE MISMATCH vector ${vi} ${name}: python=${expected} js=${got}`); }
    }
  });

  Object.keys(bundle.models).forEach((key) => {
    const got = F.forecast({ bundle, model: key, events, lat, lon, context }).magnitude;
    const expected = vec.expect[key];
    const diff = Math.abs(got - expected);
    if (diff > worst.model.diff) { worst.model = { name: `${key} (vector ${vi})`, diff }; }
    if (diff > (PRED_TOL[key] !== undefined ? PRED_TOL[key] : 1e-5)) {
      predFail += 1;
      if (predFail <= 8) { console.log(`  PREDICTION MISMATCH vector ${vi} ${key}: python=${expected} js=${got}`); }
    }
  });
});

console.log(`\nvectors            ${bundle.vectors.length}`);
console.log(`feature values     ${checked} checked, ${featFail} mismatched`);
console.log(`worst feature      ${worst.feature.name} rel diff ${worst.feature.diff.toExponential(2)}`);
console.log(`model predictions  ${bundle.vectors.length * Object.keys(bundle.models).length} checked, ${predFail} mismatched`);
console.log(`worst prediction   ${worst.model.name} abs diff ${worst.model.diff.toExponential(2)}`);
console.log(`\n${featFail + predFail === 0 ? "PASS: JavaScript matches Python" : "FAIL"}`);
process.exit(featFail + predFail === 0 ? 0 : 1);
