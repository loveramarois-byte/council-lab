setup:
	./setup.sh

start:
	./start.sh

backend-test:
	cd backend && PYTHONPATH=. pytest -q

frontend-build:
	cd frontend && npm run build
