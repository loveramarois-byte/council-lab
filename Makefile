setup:
	./setup.sh

start:
	./start.sh

backend-test:
	PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -q backend/tests

frontend-build:
	cd frontend && npm run build
