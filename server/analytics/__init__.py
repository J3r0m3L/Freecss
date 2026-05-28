"""Analytics: liquidity, regression, residual, PCA, usage (DESIGN.md §15).

Phase 1 shipped the volume z-score; Phase 3 adds bucket-PCA rep selection,
per-(watch, bucket) OLS regression, BH-FDR significance filtering, and the
intraday residual computation.
"""
