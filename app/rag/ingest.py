from app.rag.pinecone_client import get_runbook_store

SAMPLE_RUNBOOKS = [
    {
        "id": "rb-db-001",
        "text": (
            "Incident: PostgreSQL Connection Pool Exhaustion (FATAL: remaining connection slots are reserved). "
            "Root Cause: Sudden traffic spike or unclosed database sessions in FastAPI/SQLAlchemy worker threads "
            "exhausted max_connections (default 100). "
            "Safe Remediation: 1) Check active idle connections using `SELECT state, count(*) FROM pg_stat_activity GROUP BY state;`. "
            "2) Terminate long-running idle-in-transaction sessions safely using `pg_terminate_backend(pid)` for idle sessions > 10m. "
            "3) Increase PgBouncer pool size or configure `pool_pre_ping=True` and `pool_recycle=1800` in SQLAlchemy. "
            "Guardrail: Never run DROP TABLE or restart the primary DB without failing over to a read replica."
        ),
        "metadata": {
            "title": "PostgreSQL Connection Pool Exhaustion",
            "domain": "database",
            "severity_hint": "P1",
        },
    },
    {
        "id": "rb-net-001",
        "text": (
            "Incident: 502 Bad Gateway / Upstream Timed Out on Nginx Reverse Proxy. "
            "Root Cause: Backend application workers (Uvicorn/Gunicorn) hung on blocking I/O or exceeded `proxy_read_timeout` (60s), "
            "causing Nginx to drop the upstream connection. "
            "Safe Remediation: 1) Inspect `/var/log/nginx/error.log` for `upstream timed out (110: Connection timed out)`. "
            "2) Verify backend container health with `docker ps` and `docker logs --tail 100 <container>`. "
            "3) Perform a rolling restart of the app container and tune `proxy_read_timeout` if long-running endpoints are expected."
        ),
        "metadata": {
            "title": "Nginx 502 Bad Gateway & Upstream Timeout",
            "domain": "network",
            "severity_hint": "P1",
        },
    },
    {
        "id": "rb-auth-001",
        "text": (
            "Incident: Mass 401 Unauthorized Failures After JWT Signing Key Rotation. "
            "Root Cause: Auth service rotated the RS256 private signing key, but downstream API gateways cached the stale JWKS public key "
            "beyond its TTL, rejecting valid tokens with `SignatureVerificationError`. "
            "Safe Remediation: 1) Confirm JWKS endpoint (`/.well-known/jwks.json`) serves both old and new `kid` values during rotation. "
            "2) Flush the API gateway JWKS cache or restart the auth middleware pods. "
            "3) Verify token validation with a freshly minted test JWT."
        ),
        "metadata": {
            "title": "JWT 401 Spike During Key Rotation",
            "domain": "auth",
            "severity_hint": "P1",
        },
    },
    {
        "id": "rb-app-001",
        "text": (
            "Incident: Container CrashLoopBackOff / Exit Code 137 (OOMKilled). "
            "Root Cause: Python worker process exceeded Docker/Kubernetes memory limit (e.g., 512MB–1GB) due to loading large files "
            "or unbounded in-memory caching. "
            "Safe Remediation: 1) Confirm OOM event via `docker inspect <container> --format='{{.State.OOMKilled}}'` or `dmesg | grep -i oom`. "
            "2) Stream large payloads in chunks instead of reading full files into RAM. "
            "3) Reduce Uvicorn worker count (`--workers 1`) or increase container memory limits."
        ),
        "metadata": {
            "title": "Docker Container Exit Code 137 (OOMKilled)",
            "domain": "application",
            "severity_hint": "P2",
        },
    },
    {
        "id": "rb-db-002",
        "text": (
            "Incident: Redis Cache Latency Spike & ConnectionRefusedError. "
            "Root Cause: Redis hit `maxmemory` limit with `noeviction` policy, or background RDB snapshotting blocked the main thread. "
            "Safe Remediation: 1) Run `redis-cli info memory` to check `used_memory_human` vs `maxmemory`. "
            "2) Switch eviction policy to `allkeys-lru` for cache-only instances. "
            "3) Enable circuit-breaker fallback in the app so cache misses degrade gracefully to the primary DB."
        ),
        "metadata": {
            "title": "Redis MaxMemory & Latency Spike",
            "domain": "database",
            "severity_hint": "P2",
        },
    },
]


def ingest_runbooks() -> None:
    store = get_runbook_store()
    count = store.upsert_runbooks(SAMPLE_RUNBOOKS)
    print(f"Successfully upserted {count} runbooks into Pinecone.")


if __name__ == "__main__":
    ingest_runbooks()