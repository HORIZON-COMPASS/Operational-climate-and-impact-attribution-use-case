# Counterfactual crop-model static inputs

Supply the same training table and the same licensed provincial boundary files as in the factual branch:

- `monthy_climate_original_yields.csv`;
- `voivodeships.shp` and its sidecar files, including the `nazwa` attribute.

Using different static inputs between branches invalidates the factual/counterfactual comparison. These files are ignored by Git.
