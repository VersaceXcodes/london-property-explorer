# Source Data Profile — Validated June 2026 Snapshot

This document records the direct inspection results for the two local source files used to design the pipeline. It is evidence for the checks in `SPEC.md`; it is not a substitute for the generated `pipeline/output/source-manifest.json` produced by every pipeline run.

## 1. Source identity

| Source | Bytes | SHA-256 |
|---|---:|---|
| `pp-complete.csv` | 5,466,198,169 | `3978dbd0da5439112c49839d0cb7c67b2bdef5b119207589d4796c776a57c0a9` |
| `ONSPD_Online_Latest_Centroids_-966716609290186519.csv` | 1,341,515,251 | `1ed3013cecac3aeab3cd7d5842ffcc819e754a71ae7bd256928d31ace2cf7c57` |

Exact checkpoint counts in this document apply only when these hashes match. A different official snapshot is allowed, but it must produce a new committed manifest and pass the drift gates in `SPEC.md` §3.3.

## 2. File-level inspection

| Check | PPD | ONSPD |
|---|---:|---:|
| Data rows | 31,270,275 | 2,723,596 |
| Columns | 16, no header | 60, header present |
| Malformed CSV rows found | 0 | 0 |
| Duplicate `PCDS` values | — | 0 exact; 0 after canonicalisation |

The full PPD source spans 1995-01-01 through 2026-04-30. The application snapshot starts at 2021-01-01.

## 3. PPD filter profile

The exact pre-join filter in `SPEC.md` selects **466,398 rows** across **105,151 canonical postcodes**.

| Field | Observed values |
|---|---|
| Property type | `D` 22,436 · `S` 69,144 · `T` 126,741 · `F` 248,077 · `O` 0 |
| New build | `Y` 39,975 · `N` 426,423 |
| Tenure | `F` 213,281 · `L` 253,117 |

Address-field inspection over all 466,398 selected rows:

| Field | Blank rows | Maximum source length |
|---|---:|---:|
| postcode | 0 | 8 |
| paon | 0 | 46 |
| saon | 289,864 | 40 |
| street | 6 | 32 |
| locality | 436,777 | 22 |
| town/city | 0 | 20 |

`saon` and `street` therefore must remain nullable. `locality` is intentionally not stored. The pipeline must still validate enum domains and nullability on every run instead of assuming future snapshots match this profile.

## 4. Join and geography profile

| Checkpoint | Rows | Unique postcodes |
|---|---:|---:|
| PPD pre-join selection | 466,398 | 105,151 |
| Missing from ONSPD | 3 | 3 |
| ONSPD LAD outside `E09000001`–`E09000033` | 27 | 18 |
| **Final London load** | **466,368** | **105,130** |
| Final rows on terminated postcodes | 35 | 29 |

Row-level ONSPD join coverage before LAD validation is **99.99936%**. The final coordinate bounds are longitude **-0.498166 to 0.309380** and latitude **51.293400 to 51.685420**. No final London row has an unparseable or out-of-range coordinate.

The complete ONSPD file does contain 24,203 rows with latitude outside the valid WGS84 range, so numeric parsing alone is insufficient. The pipeline must reject coordinates outside longitude `[-180, 180]` or latitude `[-90, 90]`, then apply the London LAD allowlist. It must log the final bounds and abort if any retained row is outside the broad UK sanity box longitude `[-9, 3]`, latitude `[49, 61]`.

## 5. Re-run gates

For matching source hashes, every exact count above is an assertion. For a newer official snapshot, the pipeline must instead require all of the following and emit the new values in its manifest:

- no malformed PPD rows and no duplicate canonical ONSPD postcode keys;
- only documented PPD enum values after filtering (`D/S/T/F/O`, `Y/N`, `F/L`);
- final row count 400,000–550,000 and row-level postcode join coverage at least 99.9%;
- zero retained invalid coordinates and zero retained LAD codes outside the London allowlist;
- canonical ASCII postcodes no longer than 8 bytes;
- source and final min/max dates, every exclusion count, unique-postcode counts, terminated-postcode counts, and final coordinate bounds recorded.
