module.exports = {
  daemon: true,
  run: [
    {
      method: "shell.run",
      params: {
        venv: "venv",
        env: {
          PYTHONPATH: ".."
        },
        message: [
          "python -m AGENT_Joko.dashboard.server --host 127.0.0.1 --port 0"
        ],
        on: [{
          event: "/(http:\\/\\/[0-9.:]+)/",
          done: true
        }]
      }
    },
    {
      method: "local.set",
      params: {
        url: "{{input.event[1]}}"
      }
    },
    {
      when: "{{args.autopen}}",
      method: "web.open",
      params: {
        uri: "{{local.url}}"
      }
    }
  ]
}
