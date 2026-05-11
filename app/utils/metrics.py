"""app/utils/metrics.py — Prometheus metrics exposed via /metrics."""
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response

# ---------------------------------------------------------------------------
# Pre-existing counters / histograms
# ---------------------------------------------------------------------------

predict_counter = Counter(
    "hsn_predictions_total",
    "Total HSN predictions served",
    ["confidence_label"],
)

predict_latency = Histogram(
    "hsn_prediction_latency_ms",
    "HSN prediction latency in milliseconds",
    buckets=[10, 25, 50, 100, 250, 500],
)

# ---------------------------------------------------------------------------
# GST sync gauges
# ---------------------------------------------------------------------------

gst_sync_last_run_timestamp = Gauge(
    "gst_sync_last_run_timestamp",
    "Unix timestamp of the last successful GST rate sync",
)

gst_sync_updated_total = Gauge(
    "gst_sync_updated_total",
    "Number of HSN codes whose GST rate was updated in the last sync run",
)

# ---------------------------------------------------------------------------
# CBIC scrape failure counter
# ---------------------------------------------------------------------------

gst_cbic_scrape_failures_total = Counter(
    "gst_cbic_scrape_failures_total",
    "Total number of times the CBIC live scrape failed and fell back to a static source",
    ["fallback_source"],
)

# ---------------------------------------------------------------------------
# /metrics endpoint handler
# ---------------------------------------------------------------------------

async def metrics_endpoint(request: Request) -> Response:
    """Return Prometheus text format metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
