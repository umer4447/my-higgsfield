# The worker shares the API image and overrides the command. Kept as a separate
# file so a platform that wants one Dockerfile per service has one.
FROM darkroom-api:latest
CMD ["python", "-m", "app.workers.tasks"]
