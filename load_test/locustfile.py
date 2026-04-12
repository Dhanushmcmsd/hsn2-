from locust import HttpUser, task, between
import os

API_KEY = os.getenv("API_KEY", "dev-api-key")


class HSNUser(HttpUser):
    wait_time = between(0.5, 2)
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    @task(10)
    def predict(self):
        self.client.post("/predict", json={"text": "laptop computer notebook"}, headers=self.headers)

    @task(3)
    def health(self):
        self.client.get("/health")

    @task(1)
    def review_pending(self):
        self.client.get("/review/pending", headers=self.headers)
