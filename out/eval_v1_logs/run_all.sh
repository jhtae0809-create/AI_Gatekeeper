#!/bin/zsh
# Full API runs for Gatekeeper_v1.ipynb, one process per model. Same G.run calls as the notebook; rerun to retry errors.
cd "$(dirname "$0")/../../scripts"
for m in openai/gpt-6-luna anthropic/claude-haiku-5.5 google/gemini-2.5-flash-lite meta-llama/llama-3.1-8b-instruct deepseek/deepseek-chat; do
  n=${m//\//_}
  python3 -c "import gate as G
for e in ['A','B1','P_PII','P_CRED','P_HARM']: G.run(e, ['$m'])" >> ../out/eval_v1_logs/$n.log 2>&1 &
done
python3 -c "import gate as G
for e in ['A','B1','JEVQ']: G.run(e, ['jev'])" >> ../out/eval_v1_logs/jev.log 2>&1 &
wait
