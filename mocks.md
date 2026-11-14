# Offline Mock Strategy
- When `MOCK_VERTEX_VEO=true`, the Celery worker bypasses live Vertex AI billing and copies a 2-second local 9:16 sample `.mp4` fixture into the Remotion compositor so the full render pipeline is testable in CI.
