# World Router Rules

World Router V2 routes tasks by extracted features, task labels, SafetyGate, scored candidates, conflict resolution, and project policy.

Default policy:

- Docs, README, comments, and simple test changes: ClaudeCodeWorker + `deepseek_pro` or `deepseek_flash`.
- Routine coding and simple bugfixes: ClaudeCodeWorker + `deepseek_pro`.
- High-risk auth/payment/database/production code changes: ClaudeCodeWorker + `deepseek_pro`, with hard approval or OpenCode escalation when required.
- Multimodal analysis: MiMoWorker + `mimo_multimodal`.
- Screenshot-to-code work: MiMoWorker extracts constraints, then ClaudeCodeWorker implements code changes when the task requires it.
- Explicit GLM-5.2, `complex_coding`, or `hard_bugfix`: OpenCodeWorker + `opencode-go/glm-5.2`.

Permanent constraints:

- ClaudeCodeWorker only uses DeepSeek or MiMo.
- ClaudeCodeWorker never uses GLM, GLM-5.2, Z.AI GLM, or ChatGLM.
- GLM-5.2 only runs through OpenCodeWorker.
- OpenCodeWorker omits `--variant` for default; never construct `--variant default`.
- Do not introduce Hermes.
- Do not auto-merge.
- Do not force push.
- Do not modify forbidden paths.
- Do not commit or print secrets.
- Do not execute dangerous commands or permission-bypass flags.
