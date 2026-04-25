from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response

predict_counter = Counter("hsn_predictions_total", "Total predictions", ["confidence_label"])
predict_latency = Histogram("hsn_prediction_latency_ms", "Prediction latency", buckets=[10, 25, 50, 100, 250, 500])


async def metrics_endpoint(request: Request) -> Response:
    # TODO: Wire this endpoint into app/main.py router registration.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
