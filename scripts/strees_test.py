import asyncio
import argparse
import time
import httpx


PAYLOAD = {
    "event_id": "STRESS-TEST",
    "disaster_type": "earthquake",
    "severity": 6.8,
    "aftershock_risk": "HIGH",
    "tsunami_risk": False,
    "zone": "red",
    "batch_index": 1,
    "devices": [
        {
            "phone": "+212600000000",
            "latitude": 31.6,
            "longitude": -8.0,
            "location_radius_m": 100,
            "last_location_time": "2026-09-23T10:00:00Z",
            "reachability_status": "CONNECTED_SMS",
            "last_status_time": "2026-09-23T10:01:00Z",
            "zone": "red",
            "distance_km": 2.1,
        }
    ],
    "nearest_shelters": [
        {
            "name": "Test Shelter",
            "address": "Test Address",
            "location": {
                "latitude": 31.61,
                "longitude": -8.01,
            },
            "distance_km": 1.2,
            "capacity": 500,
        }
    ],
    "network_status": {
        "congestion_level": "HIGH",
        "sms_delivery_rate": 0.5,
        "qos_status": "active",
    },
}


def percentile(values, percent):
    if not values:
        return 0

    values = sorted(values)
    index = int((len(values) - 1) * percent)

    return values[index]


def is_fallback(data):
    for decision in data.get("decisions", []):
        reasoning = decision.get("reasoning", "")

        if reasoning.startswith("Rule-based fallback"):
            return True

    return False


async def send_request(client, semaphore, url):
    async with semaphore:
        start = time.perf_counter()

        try:
            response = await client.post(url, json=PAYLOAD)

            latency = time.perf_counter() - start

            if response.status_code != 200:
                return {
                    "success": False,
                    "fallback": False,
                    "latency": latency,
                    "error": f"HTTP {response.status_code}",
                }

            data = response.json()

            return {
                "success": True,
                "fallback": is_fallback(data),
                "latency": latency,
                "error": None,
            }

        except Exception as error:
            return {
                "success": False,
                "fallback": False,
                "latency": time.perf_counter() - start,
                "error": str(error),
            }


async def run_test(total_requests, concurrency, url):
    semaphore = asyncio.Semaphore(concurrency)

    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )

    async with httpx.AsyncClient(
        timeout=120,
        limits=limits,
    ) as client:

        print(f"\nSending {total_requests} requests")
        print(f"Concurrency: {concurrency}")
        print(f"Endpoint: {url}")

        start = time.perf_counter()

        tasks = [
            send_request(client, semaphore, url)
            for _ in range(total_requests)
        ]

        results = await asyncio.gather(*tasks)

        duration = time.perf_counter() - start

    successful = sum(result["success"] for result in results)
    failed = total_requests - successful

    fallback_count = sum(
        result["fallback"]
        for result in results
    )

    ai_count = successful - fallback_count

    latencies = [
        result["latency"]
        for result in results
        if result["success"]
    ]

    print("\n========== RESULTS ==========")
    print(f"Total requests:     {total_requests}")
    print(f"Successful:         {successful}")
    print(f"Failed:             {failed}")
    print(f"AI responses:       {ai_count}")
    print(f"Fallback responses: {fallback_count}")
    print(f"Total time:         {duration:.2f}s")
    print(f"Requests/sec:       {total_requests / duration:.2f}")

    if latencies:
        print(f"Average latency:    {sum(latencies) / len(latencies):.2f}s")
        print(f"P50 latency:        {percentile(latencies, 0.50):.2f}s")
        print(f"P95 latency:        {percentile(latencies, 0.95):.2f}s")
        print(f"P99 latency:        {percentile(latencies, 0.99):.2f}s")

    errors = [
        result["error"]
        for result in results
        if result["error"]
    ]

    if errors:
        print("\nFirst errors:")

        for error in errors[:10]:
            print(f"- {error}")


async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "requests",
        type=int,
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--url",
        default="http://localhost:5001/decide",
    )

    args = parser.parse_args()

    await run_test(
        args.requests,
        args.concurrency,
        args.url,
    )


if __name__ == "__main__":
    asyncio.run(main())