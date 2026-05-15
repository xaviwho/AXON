# AXON service template

Copy this directory to bootstrap a new layer service. Each service is a thin FastAPI
app with a `/health` endpoint. Until Prompts 2+ fill them in, every layer service in
`docker-compose.yml` runs this same image with a unique `AXON_SERVICE_NAME` env var.
