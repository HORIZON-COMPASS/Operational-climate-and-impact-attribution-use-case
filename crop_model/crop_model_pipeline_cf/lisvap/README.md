# Counterfactual LISVAP runtime

Provide a `config/config.xml` and basemaps identical to the factual branch. The pipeline populates `meteo/` from `daily-data/step_10_cf` and writes products to `output/`.

All runtime data are ignored by Git. Preserve the exact configuration and input checksums with every run.
