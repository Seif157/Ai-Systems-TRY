# Calibration and holdout construction guide

Split by document or policy family before reviewing metrics. Keep translations and paraphrases in
one partition. Select thresholds using calibration only, freeze the corpus and labels, then execute
holdout once. Any source, label, scope, chunker, model, runtime, or policy change invalidates prior
fingerprints and metrics. Holdout observations must never be used for iterative tuning.
