# StockWise AI — Codex Development Instructions

## Project objective
Build an AI-assisted inventory and procurement management
application for African SMEs, initially targeting Lesotho.

## Required reading
- Read docs/PRD.md before implementing features.
- Follow the PRD as the product source of truth.
- Read the README before making architectural changes.

## Architecture
- Backend: Python, FastAPI, Pydantic, SQLAlchemy.
- Frontend: React, Vite, Tailwind CSS, Recharts.
- Database: SQLite for the MVP.
- Tests: Pytest and appropriate frontend tests.
- Deployment: Docker and Docker Compose.

## Engineering rules
1. Keep business logic separate from API routes.
2. Use deterministic, testable inventory calculations.
3. Validate all API inputs.
4. Maintain traceable stock movement records.
5. Prevent negative stock through normal stock-out operations.
6. Never invent inventory, sales, supplier or purchasing data.
7. Keep AI services separate from core inventory operations.
8. AI must not independently modify stock or approve purchases.
9. Require human approval for purchasing recommendations.
10. Keep secrets in environment variables.
11. Never commit .env files, credentials or API keys.
12. Write automated tests for new business logic.
13. Avoid implementing features outside the MVP without approval.

## Codex workflow
Before implementing a task:
- Inspect the existing project.
- Explain the proposed implementation briefly.
- Identify files to create or modify.
- Implement only the requested scope.

After implementation:
- Run relevant tests.
- Report modified files.
- Report test results.
- Identify outstanding issues.
- Do not claim success without verification.

## Development principle
Prefer a small, complete, reliable implementation over
a large collection of incomplete features.