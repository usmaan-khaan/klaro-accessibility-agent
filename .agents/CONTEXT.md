# Secure Coding Standards & Development Guidelines

This project enforces strict security and coding standards. All agents, developers, and tools must adhere to these policies.

## 1. Input Validation and Type Safety
- **Rule**: All structured inputs and outputs (including event payloads and configuration schemas) must be validated using **Pydantic** models.
- **Rule**: Avoid raw, untyped JSON processing or dictionary access for critical data paths. Use `pydantic.BaseModel` to define data models.
- **Rule**: Validate incoming payloads at the boundaries of FastAPIs and ADK functional nodes.

## 2. Command Execution Safety
- **Rule**: Raw shell executions (e.g., `os.system`, `subprocess.Popen(..., shell=True)`, or raw strings in `subprocess.run`) are strictly **prohibited**.
- **Rule**: To run processes or commands, use structured execution APIs like `subprocess.run` with list arguments (e.g., `["git", "commit"]`) and disable shell evaluation.
- **Rule**: Sanitize any file paths or system inputs before using them in filesystem operations.

## 3. Git Hooks and Pre-Commit Remediation
- **Rule**: Every developer and autonomous agent change must run pre-commit hooks configured in `.pre-commit-config.yaml`.
- **Rule**: Pre-commit hooks run automated linting, code formatting, and static security checks using **Semgrep**.
- **Rule**: Any code containing hardcoded credentials, API keys, or security violations will be blocked by the git pre-commit hooks and must be healed before committing.
