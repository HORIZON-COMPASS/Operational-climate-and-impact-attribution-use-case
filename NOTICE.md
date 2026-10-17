# Third-party notices and data provenance

## ATTRICI

This repository redistributes a frozen, project-specific compatibility snapshot derived from ATTRICI, originally developed by Matthias Mengel, Simon Treu, and contributors. The snapshot preserves the execution path used by the COMPASS demonstrator; it is not an upstream release or a new general-purpose ATTRICI version. The upstream project is available at <https://github.com/ISI-MIP/attrici> and is licensed under GNU GPL v3.

The redistributed source is under `vendor/attrici`. Its upstream base and COMPASS changes are documented in `ATTRICI_MODIFICATIONS.md`. Copyright remains with the respective contributors.

## Grouped time-series cross-validation

The crop-model implementation contains a grouped time-series split adapted from scikit-learn source code. The source reference is retained in both crop-model `modeling.py` files. scikit-learn is distributed under the BSD 3-Clause licence; the required notice is included in `licenses/scikit-learn-BSD-3-Clause.txt`.

## Administrative boundary data

Administrative boundary data are not included in this release. Users must supply a compatible Polish voivodeship dataset and comply with its licence. Record the provider, version/date, coordinate reference system, and any transformation applied.
