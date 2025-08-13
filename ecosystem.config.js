module.exports = {
  apps: [
    {
      name: "fastapi-chat",
      script: "uvicorn",
      args: "main:app --host 0.0.0.0 --port 8000",
      interpreter: "python3",
      cwd: "/home/huanvm/chat-app",
      env: {
        PYTHONPATH: "."
      }
    }
  ]
}
