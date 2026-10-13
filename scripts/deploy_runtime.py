"""Update an explicitly named Klaro Agent Runtime with frozen dependencies."""

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import vertexai


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--engine", required=True, help="Existing full reasoningEngine resource name")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    if not args.engine.startswith("projects/") or f"/locations/{args.region}/reasoningEngines/" not in args.engine:
        parser.error("Engine resource must belong to the selected region.")
    requirements = root / "app/app_utils/.requirements.txt"
    subprocess.run([
        "uv", "export", "--locked", "--no-hashes", "--no-header", "--no-dev",
        "--no-emit-project", "--no-sources", "--output-file", str(requirements),
    ], check=True, capture_output=True, text=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    client = vertexai.Client(project=args.project, location=args.region)
    existing = client.agent_engines.get(name=args.engine)
    if existing.api_resource.display_name != "accessibility-shield":
        raise ValueError("Refusing to update an unrelated agent.")
    # Preserve the platform's existing API schema; the entrypoint contract is unchanged.
    class_methods = existing.api_resource.spec.class_methods
    env_vars = {item.name: item.value for item in (existing.api_resource.spec.deployment_spec.env or [])}
    # Agent Runtime injects these reserved coordinates itself.
    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_QUOTA_PROJECT",
                 "GOOGLE_CLOUD_LOCATION", "PORT", "K_SERVICE", "K_REVISION",
                 "K_CONFIGURATION", "GOOGLE_APPLICATION_CREDENTIALS"):
        env_vars.pop(name, None)
    env_vars.update({"KLARO_MODEL_LOCATION": "global",
                     "GOOGLE_GENAI_USE_VERTEXAI": "True",
                     "PLAYWRIGHT_BROWSERS_PATH": "/opt/klaro-browsers",
                     "NUM_WORKERS": "1",
                     "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false"})
    labels = dict(existing.api_resource.labels or {})
    labels["source_commit"] = commit
    logging.basicConfig(level=logging.INFO)
    print(f"Updating {args.engine} from {commit}", flush=True)
    remote = client.agent_engines.update(name=args.engine, config={
        "source_packages": ["app", "installation_scripts/install_chromium.sh"],
        "entrypoint_module": "app.agent_runtime_app",
        "entrypoint_object": "agent_runtime",
        "requirements_file": "app/app_utils/.requirements.txt",
        "class_methods": class_methods,
        "python_version": "3.12",
        "build_options": {"installation_scripts": ["installation_scripts/install_chromium.sh"]},
        "agent_framework": "google-adk",
        "env_vars": env_vars,
        "min_instances": 1, "max_instances": 1,
        "container_concurrency": 4,
        "resource_limits": {"cpu": "2", "memory": "4Gi"},
        "labels": labels,
    })
    metadata = {"remote_agent_runtime_id": remote.api_resource.name,
                "deployment_target": "agent_runtime", "source_commit": commit}
    (root / "deployment_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
