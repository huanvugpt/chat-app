module.exports = {
  apps: [
    {
      name: "fastapi-chat",
      script: "uvicorn",
      args: "main:app --host 0.0.0.0 --port 8000 --reload",
      interpreter: "python3",
      watch: false,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONPATH: "."
      }
    }
  ]
};
