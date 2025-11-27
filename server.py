"""
AI Orchestrator - Smart routing between local Ollama (free) and RunPod (GPU)

Routes:
- Text/Code: Ollama (free, local CPU) or RunPod vLLM (paid, fast GPU)
- Images: RunPod Automatic1111/ComfyUI
- Video: RunPod Wan2.2
- Audio: RunPod WhisperX
"""

import os
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Literal
from enum import Enum

# Config
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "rpa_YYOARL5MEBTTKKWGABRKTW2CVHQYRBTOBZNSGIL3lwwfdz")
RUNPOD_API_BASE = "https://api.runpod.ai/v2"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# RunPod endpoints (paid GPU)
ENDPOINTS = {
    "video": {"id": "4jql4l7l0yw0f3", "name": "Wan2.2 Video", "type": "video"},
    "image": {"id": "tzf1j3sc3zufsy", "name": "Automatic1111 SD", "type": "image"},
    "comfyui": {"id": "5zurj845tbf8he", "name": "ComfyUI", "type": "image"},
    "whisper": {"id": "lrtisuv8ixbtub", "name": "WhisperX", "type": "audio"},
    "llm": {"id": "03g5hz3hlo8gr2", "name": "vLLM", "type": "text"},
}

# Ollama models (free local CPU)
OLLAMA_MODELS = {
    "llama3.2": {"name": "Llama 3.2 3B", "context": 128000, "size": "3B"},
    "llama3.2:1b": {"name": "Llama 3.2 1B", "context": 128000, "size": "1B"},
    "qwen2.5-coder:7b": {"name": "Qwen 2.5 Coder 7B", "context": 32000, "size": "7B"},
    "mistral": {"name": "Mistral 7B", "context": 32000, "size": "7B"},
    "phi3": {"name": "Phi-3 Mini", "context": 128000, "size": "3.8B"},
}

app = FastAPI(
    title="AI Orchestrator",
    description="Smart routing between local Ollama (free) and RunPod (GPU)",
    version="1.0.0",
)

# CORS middleware for web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store recent jobs
recent_jobs = []

# Track cost savings
cost_tracker = {
    "ollama_requests": 0,
    "runpod_requests": 0,
    "estimated_savings": 0.0,  # USD saved by using Ollama
}


# ============== Ollama Functions (FREE local inference) ==============

async def ollama_health() -> dict:
    """Check Ollama service health"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": "healthy",
                    "models": [m["name"] for m in data.get("models", [])],
                }
            return {"status": "unhealthy", "error": f"Status {resp.status_code}"}
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}


async def ollama_generate(
    prompt: str,
    model: str = "llama3.2",
    system: Optional[str] = None,
    stream: bool = False,
    options: Optional[dict] = None,
) -> dict:
    """Generate text using local Ollama"""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json=payload,
                timeout=300,  # 5 min timeout for long generations
            )
            result = resp.json()
            # Track usage
            cost_tracker["ollama_requests"] += 1
            cost_tracker["estimated_savings"] += 0.001  # ~$0.001 saved per request vs RunPod
            return result
        except Exception as e:
            return {"error": str(e)}


async def ollama_chat(
    messages: List[dict],
    model: str = "llama3.2",
    stream: bool = False,
    options: Optional[dict] = None,
) -> dict:
    """Chat completion using local Ollama"""
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if options:
        payload["options"] = options

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=300,
            )
            result = resp.json()
            cost_tracker["ollama_requests"] += 1
            cost_tracker["estimated_savings"] += 0.001
            return result
        except Exception as e:
            return {"error": str(e)}


async def ollama_pull_model(model: str) -> dict:
    """Pull/download a model to Ollama"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model},
                timeout=600,  # Models can take a while to download
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


def build_comfyui_workflow(
    prompt: str,
    negative_prompt: str = "",
    seed: int = 42,
    steps: int = 20,
    cfg: float = 1.0,  # Flux uses low CFG (1.0)
    width: int = 1024,
    height: int = 1024,
    sampler: str = "euler",
    scheduler: str = "simple",
    denoise: float = 1.0,
    model: str = "flux1-dev-fp8.safetensors",
) -> dict:
    """Build a ComfyUI Flux txt2img workflow in API format"""
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": model
            }
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "height": height,
                "width": width
            }
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": prompt
            }
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": negative_prompt
            }
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": cfg,
                "denoise": denoise,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": sampler,
                "scheduler": scheduler,
                "seed": seed,
                "steps": steps
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "ComfyUI",
                "images": ["8", 0]
            }
        }
    }


async def get_endpoint_health(endpoint_id: str) -> dict:
    """Get health status of a RunPod endpoint"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{RUNPOD_API_BASE}/{endpoint_id}/health",
                headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


async def get_job_status(endpoint_id: str, job_id: str) -> dict:
    """Get status of a specific job"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{RUNPOD_API_BASE}/{endpoint_id}/status/{job_id}",
                headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


async def submit_job(endpoint_id: str, payload: dict) -> dict:
    """Submit a job to a RunPod endpoint"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{RUNPOD_API_BASE}/{endpoint_id}/run",
                headers={
                    "Authorization": f"Bearer {RUNPOD_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"input": payload},
                timeout=30,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Main dashboard showing all endpoint statuses"""

    # Fetch all endpoint health in parallel
    health_tasks = {
        name: get_endpoint_health(ep["id"])
        for name, ep in ENDPOINTS.items()
    }

    health_results = {}
    for name, task in health_tasks.items():
        health_results[name] = await task

    # Get Ollama status
    ollama_status = await ollama_health()

    # Build HTML
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Orchestrator Dashboard</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body { font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
            h1 { color: #00d9ff; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
            .card { background: #16213e; border-radius: 10px; padding: 20px; }
            .card h3 { margin-top: 0; color: #00d9ff; }
            .status { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
            .status.ready { background: #00c853; color: #000; }
            .status.throttled { background: #ff9800; color: #000; }
            .status.idle { background: #2196f3; color: #fff; }
            .status.error { background: #f44336; color: #fff; }
            .metric { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #333; }
            .metric:last-child { border-bottom: none; }
            .metric-value { font-weight: bold; color: #00d9ff; }
            .timestamp { color: #666; font-size: 12px; margin-top: 20px; }
            .test-btn { background: #00d9ff; color: #000; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 10px; }
            .test-btn:hover { background: #00b8d4; }
        </style>
    </head>
    <body>
        <h1>🤖 AI Orchestrator Dashboard</h1>
        <p class="timestamp">Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """ (auto-refreshes every 10s)</p>

        <div class="stats-bar" style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">
            <div class="stat-card" style="background: #16213e; padding: 15px 25px; border-radius: 10px;">
                <span style="color: #888;">Ollama Status</span>
                <span class="metric-value" style="display: block; font-size: 24px; color: """ + ("#00c853" if ollama_status.get("status") == "healthy" else "#f44336") + """;">""" + ollama_status.get("status", "unknown").upper() + """</span>
            </div>
            <div class="stat-card" style="background: #16213e; padding: 15px 25px; border-radius: 10px;">
                <span style="color: #888;">Free Requests (Ollama)</span>
                <span class="metric-value" style="display: block; font-size: 24px;">""" + str(cost_tracker["ollama_requests"]) + """</span>
            </div>
            <div class="stat-card" style="background: #16213e; padding: 15px 25px; border-radius: 10px;">
                <span style="color: #888;">Paid Requests (RunPod)</span>
                <span class="metric-value" style="display: block; font-size: 24px;">""" + str(cost_tracker["runpod_requests"]) + """</span>
            </div>
            <div class="stat-card" style="background: #16213e; padding: 15px 25px; border-radius: 10px;">
                <span style="color: #888;">Est. Savings</span>
                <span class="metric-value" style="display: block; font-size: 24px; color: #00c853;">$""" + str(round(cost_tracker["estimated_savings"], 2)) + """</span>
            </div>
        </div>

        <div class="grid">
    """

    for name, ep in ENDPOINTS.items():
        health = health_results.get(name, {})
        workers = health.get("workers", {})
        jobs = health.get("jobs", {})

        # Determine status
        if "error" in health:
            status_class = "error"
            status_text = "Error"
        elif workers.get("ready", 0) > 0 or workers.get("running", 0) > 0:
            status_class = "ready"
            status_text = "Ready"
        elif workers.get("throttled", 0) > 0:
            status_class = "throttled"
            status_text = "Throttled (waiting for GPU)"
        elif workers.get("idle", 0) > 0:
            status_class = "idle"
            status_text = "Idle"
        else:
            status_class = "idle"
            status_text = "Standby"

        html += f"""
            <div class="card">
                <h3>{ep['name']}</h3>
                <span class="status {status_class}">{status_text}</span>
                <p style="color: #888; font-size: 12px;">Type: {ep['type']} | ID: {ep['id'][:8]}...</p>

                <div class="metric"><span>Workers Ready</span><span class="metric-value">{workers.get('ready', 0)}</span></div>
                <div class="metric"><span>Workers Running</span><span class="metric-value">{workers.get('running', 0)}</span></div>
                <div class="metric"><span>Workers Initializing</span><span class="metric-value">{workers.get('initializing', 0)}</span></div>
                <div class="metric"><span>Workers Throttled</span><span class="metric-value">{workers.get('throttled', 0)}</span></div>
                <div class="metric"><span>Jobs In Queue</span><span class="metric-value">{jobs.get('inQueue', 0)}</span></div>
                <div class="metric"><span>Jobs In Progress</span><span class="metric-value">{jobs.get('inProgress', 0)}</span></div>
                <div class="metric"><span>Jobs Completed</span><span class="metric-value">{jobs.get('completed', 0)}</span></div>
                <div class="metric"><span>Jobs Failed</span><span class="metric-value">{jobs.get('failed', 0)}</span></div>

                <a href="/test/{name}"><button class="test-btn">Test Endpoint</button></a>
            </div>
        """

    html += """
        </div>

        <h2 style="margin-top: 40px;">Recent Jobs</h2>
        <div class="card">
    """

    if recent_jobs:
        for job in recent_jobs[-10:][::-1]:
            html += f"""<div class="metric">
                <span>{job['endpoint']} - {job['id'][:16]}...</span>
                <span class="metric-value">{job['status']}</span>
            </div>"""
    else:
        html += "<p style='color: #666;'>No jobs submitted yet</p>"

    html += """
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


@app.get("/api/health")
async def api_health():
    """API endpoint to get all endpoint health"""
    results = {}
    for name, ep in ENDPOINTS.items():
        results[name] = await get_endpoint_health(ep["id"])
    return results


@app.get("/api/status/{endpoint}/{job_id}")
async def api_job_status(endpoint: str, job_id: str):
    """Get status of a specific job"""
    if endpoint not in ENDPOINTS:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return await get_job_status(ENDPOINTS[endpoint]["id"], job_id)


@app.get("/test/{endpoint}")
async def test_endpoint(endpoint: str):
    """Submit a test job to an endpoint"""
    if endpoint not in ENDPOINTS:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    ep = ENDPOINTS[endpoint]

    # Different test payloads for different endpoint types
    if ep["type"] == "video":
        payload = {
            "prompt": "A cat walking through a garden, cinematic lighting, high quality",
            "negative_prompt": "blurry, low quality, distorted",
            "seed": 42,
            "cfg": 4.0,
            "steps": 20,
            "width": 832,
            "height": 480,
            "num_frames": 81,
            "length": 81
        }
    elif ep["type"] == "image":
        if endpoint == "comfyui":
            # ComfyUI needs a workflow JSON
            payload = {
                "workflow": build_comfyui_workflow(
                    prompt="A beautiful sunset over mountains, photorealistic, 8k",
                    negative_prompt="blurry, low quality, distorted",
                    seed=42,
                    steps=20,
                    cfg=7.0,
                    width=512,
                    height=512
                )
            }
        else:
            payload = {"prompt": "A beautiful sunset over mountains, photorealistic"}
    elif ep["type"] == "audio":
        payload = {"audio_url": "https://example.com/test.mp3"}
    elif ep["type"] == "text":
        payload = {"prompt": "Hello, how are you?", "max_tokens": 50}
    else:
        payload = {"test": True}

    result = await submit_job(ep["id"], payload)

    # Track job
    if "id" in result:
        recent_jobs.append({
            "endpoint": endpoint,
            "id": result["id"],
            "status": result.get("status", "SUBMITTED"),
            "timestamp": datetime.now().isoformat(),
        })

    return result


class VideoRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = "blurry, low quality, distorted"
    seed: Optional[int] = None  # Random if not set
    cfg: Optional[float] = 4.0  # Classifier-free guidance
    steps: Optional[int] = 20
    width: Optional[int] = 832
    height: Optional[int] = 480
    num_frames: Optional[int] = 81
    length: Optional[int] = 81  # Same as num_frames for Wan2.2


class ImageRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = "blurry, low quality"
    steps: Optional[int] = 20
    width: Optional[int] = 512
    height: Optional[int] = 512


@app.post("/api/generate/video")
async def generate_video(request: VideoRequest):
    """Generate video using Wan2.2"""
    import random
    payload = request.dict()
    # Generate random seed if not provided
    if payload.get("seed") is None:
        payload["seed"] = random.randint(1, 2147483647)

    result = await submit_job(ENDPOINTS["video"]["id"], payload)
    if "id" in result:
        recent_jobs.append({
            "endpoint": "video",
            "id": result["id"],
            "status": result.get("status", "SUBMITTED"),
            "timestamp": datetime.now().isoformat(),
        })
    return result


@app.post("/api/generate/image")
async def generate_image(request: ImageRequest):
    """Generate image using Automatic1111"""
    result = await submit_job(ENDPOINTS["image"]["id"], request.dict())
    if "id" in result:
        recent_jobs.append({
            "endpoint": "image",
            "id": result["id"],
            "status": result.get("status", "SUBMITTED"),
            "timestamp": datetime.now().isoformat(),
        })
    return result


class ComfyUIRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = ""
    seed: Optional[int] = None
    steps: Optional[int] = 20
    cfg: Optional[float] = 7.0
    width: Optional[int] = 512
    height: Optional[int] = 512
    sampler: Optional[str] = "euler"
    scheduler: Optional[str] = "normal"
    workflow: Optional[Dict[str, Any]] = None  # Custom workflow override


@app.post("/api/generate/comfyui")
async def generate_comfyui(request: ComfyUIRequest):
    """Generate image using ComfyUI with workflow"""
    import random

    # Use custom workflow if provided, otherwise build default txt2img
    if request.workflow:
        workflow = request.workflow
    else:
        seed = request.seed if request.seed is not None else random.randint(1, 2147483647)
        workflow = build_comfyui_workflow(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            seed=seed,
            steps=request.steps,
            cfg=request.cfg,
            width=request.width,
            height=request.height,
            sampler=request.sampler,
            scheduler=request.scheduler,
        )

    payload = {"workflow": workflow}
    result = await submit_job(ENDPOINTS["comfyui"]["id"], payload)

    if "id" in result:
        recent_jobs.append({
            "endpoint": "comfyui",
            "id": result["id"],
            "status": result.get("status", "SUBMITTED"),
            "timestamp": datetime.now().isoformat(),
        })
    return result


# ============== Text Generation Endpoints (Smart Routing) ==============

class Priority(str, Enum):
    LOW = "low"      # Always use free Ollama
    NORMAL = "normal"  # Ollama if available, else RunPod
    HIGH = "high"    # RunPod for speed


class TextRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    model: Optional[str] = "llama3.2"  # Ollama model name
    max_tokens: Optional[int] = 2048
    temperature: Optional[float] = 0.7
    priority: Optional[Priority] = Priority.NORMAL


class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]  # [{"role": "user", "content": "..."}]
    model: Optional[str] = "llama3.2"
    max_tokens: Optional[int] = 2048
    temperature: Optional[float] = 0.7
    priority: Optional[Priority] = Priority.NORMAL


@app.post("/api/generate/text")
async def generate_text(request: TextRequest):
    """
    Generate text with smart routing:
    - LOW priority: Always Ollama (free)
    - NORMAL priority: Ollama if healthy, else RunPod
    - HIGH priority: RunPod vLLM (fast GPU)
    """
    # Check Ollama health for routing decision
    ollama_status = await ollama_health()
    use_ollama = False

    if request.priority == Priority.LOW:
        use_ollama = True
    elif request.priority == Priority.NORMAL:
        use_ollama = ollama_status.get("status") == "healthy"
    # HIGH priority always uses RunPod

    if use_ollama and ollama_status.get("status") == "healthy":
        # Use free local Ollama
        result = await ollama_generate(
            prompt=request.prompt,
            model=request.model,
            system=request.system,
            options={
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
            },
        )
        return {
            "provider": "ollama",
            "model": request.model,
            "cost": 0.0,
            "response": result.get("response", ""),
            "tokens": result.get("eval_count", 0),
        }
    else:
        # Use RunPod vLLM (paid)
        cost_tracker["runpod_requests"] += 1
        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        result = await submit_job(ENDPOINTS["llm"]["id"], payload)
        if "id" in result:
            recent_jobs.append({
                "endpoint": "llm",
                "id": result["id"],
                "status": result.get("status", "SUBMITTED"),
                "timestamp": datetime.now().isoformat(),
            })
        return {
            "provider": "runpod",
            "model": "vLLM",
            "cost": 0.001,  # Estimated per request
            "job_id": result.get("id"),
            "status": result.get("status"),
        }


@app.post("/api/chat")
async def chat_completion(request: ChatRequest):
    """
    Chat completion with smart routing
    """
    ollama_status = await ollama_health()
    use_ollama = request.priority != Priority.HIGH and ollama_status.get("status") == "healthy"

    if use_ollama:
        result = await ollama_chat(
            messages=request.messages,
            model=request.model,
            options={
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
            },
        )
        return {
            "provider": "ollama",
            "model": request.model,
            "cost": 0.0,
            "message": result.get("message", {}),
            "tokens": result.get("eval_count", 0),
        }
    else:
        # Fallback to RunPod
        cost_tracker["runpod_requests"] += 1
        # Convert chat format to prompt for vLLM
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in request.messages])
        result = await submit_job(ENDPOINTS["llm"]["id"], {"prompt": prompt})
        return {
            "provider": "runpod",
            "job_id": result.get("id"),
            "status": result.get("status"),
        }


@app.get("/api/ollama/models")
async def list_ollama_models():
    """List available Ollama models"""
    status = await ollama_health()
    return {
        "available": status.get("models", []),
        "recommended": list(OLLAMA_MODELS.keys()),
        "status": status.get("status"),
    }


@app.post("/api/ollama/pull/{model}")
async def pull_ollama_model(model: str):
    """Pull/download a model to Ollama"""
    result = await ollama_pull_model(model)
    return result


@app.get("/api/stats")
async def get_stats():
    """Get usage statistics and cost savings"""
    return {
        "ollama_requests": cost_tracker["ollama_requests"],
        "runpod_requests": cost_tracker["runpod_requests"],
        "estimated_savings_usd": round(cost_tracker["estimated_savings"], 4),
        "total_requests": cost_tracker["ollama_requests"] + cost_tracker["runpod_requests"],
        "ollama_percentage": round(
            cost_tracker["ollama_requests"] / max(1, cost_tracker["ollama_requests"] + cost_tracker["runpod_requests"]) * 100, 1
        ),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
