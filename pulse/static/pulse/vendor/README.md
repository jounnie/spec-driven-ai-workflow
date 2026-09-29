# Vendored assets

Files are copied byte for byte from the npm packages. Nothing is installed
with npm; the tarballs were downloaded from `registry.npmjs.org` and
unpacked outside the repository. Do not edit these files: a test compares
their SHA-256 with the hashes below.

| File | Package | Licence | Source | SHA-256 |
|---|---|---|---|---|
| `htmx.min.js` | htmx.org 2.0.11 (`dist/htmx.min.js`) | 0BSD | https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
| `LICENSE-htmx.txt` | htmx.org 2.0.11 (`LICENSE`) | 0BSD | https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz | `d3d2456f76414f2456104660ebd65aff1c04cd7966b942bdabd63f3cdb316a38` |
| `chart.umd.js` | chart.js 4.5.1 (`dist/chart.umd.js`) | MIT | https://registry.npmjs.org/chart.js/-/chart.js-4.5.1.tgz | `ecc3cd1eeb8c34d2178e3f59fd63ec5a3d84358c11730af0b9958dc886d7652a` |
| `chart.umd.js.map` | chart.js 4.5.1 (`dist/chart.umd.js.map`) | MIT | https://registry.npmjs.org/chart.js/-/chart.js-4.5.1.tgz | `50f788499bc584696c2344c77e91af0f80a518eca93e312ddbb8008d7525d7fa` |
| `LICENSE-chartjs.txt` | chart.js 4.5.1 (`LICENSE.md`) | MIT | https://registry.npmjs.org/chart.js/-/chart.js-4.5.1.tgz | `41a84aa2caba645f966a18d9c2056b73e6d3a81d80bc0046bc0011a2634d4cce` |

`chart.umd.js.map` is included because `chart.umd.js` ends with a
`sourceMappingURL` comment and Django's manifest storage fails on a missing
map.

## How to update

1. Download the new tarball from `registry.npmjs.org` and unpack it outside the repository.
2. Copy the files over the ones above, unchanged.
3. Update the version, source URL and SHA-256 in this table (`sha256sum <file>`).
4. Run `uv run pytest`; the hash test must pass.
