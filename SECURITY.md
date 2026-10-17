# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately to the repository maintainers, preferably through GitHub private vulnerability reporting when it is enabled. Do not disclose credentials or sensitive infrastructure details in a public issue.

## Credential handling

The workflows use the Copernicus Climate Data Store client. Store CDS credentials in the standard user-level configuration outside this repository. Never commit `.cdsapirc`, `.env`, tokens, private keys, FTP credentials, or machine-specific configuration.

This public release performs no automatic upload. Generated outputs remain local unless the user explicitly transfers them with tooling outside this repository.

Run `python scripts/release_check.py` before every release. It checks common secret patterns, personal absolute paths, unexpected scientific data files, Python syntax, and shell syntax. Pattern-based scanning is not a substitute for GitHub secret scanning or a dedicated tool such as Gitleaks.
