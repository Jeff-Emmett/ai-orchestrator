import runpod
import os

# Set API key from config
runpod.api_key = os.getenv("RUNPOD_API_KEY", "")

# Test 1: List all pods
print("=== Testing RunPod API Connection ===\n")
print("1. Listing all pods:")
pods = runpod.get_pods()
for pod in pods:
    print(f"   - {pod['name']} ({pod['id']}): {pod['desiredStatus']}")

# Test 2: Check serverless endpoints
print("\n2. Checking serverless endpoints:")
try:
    endpoints = runpod.get_endpoints()
    if endpoints:
        for endpoint in endpoints:
            print(f"   - {endpoint.get('name', 'Unnamed')}: {endpoint.get('id')}")
    else:
        print("   No serverless endpoints configured yet")
except Exception as e:
    print(f"   Note: {e}")

print("\n✅ API Connection successful!")
