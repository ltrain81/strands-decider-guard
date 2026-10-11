#!/usr/bin/env bash
# Scripted demo for screen recording: runs five scenes with Claude Code (-p), typing each prompt
# out first so it reads well on video. Uses demo/en or demo/ko data (all synthetic).
#
#   demo/run_demo.sh              all scenes, press Enter to advance
#   demo/run_demo.sh 3 4          only scenes 3 and 4
#   AUTO=4 demo/run_demo.sh       advance automatically after 4 s
#   DEMO_LANG=ko demo/run_demo.sh Korean prompts and data (default: from LANG)
#   MODEL=sonnet SETTINGS=/path/settings.json demo/run_demo.sh   (extra Claude Code settings, e.g. hooks)
#
# Needs the hooks installed (make local / client/install.sh), or SETTINGS pointing at a settings file with them.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO_LANG="${DEMO_LANG:-$(case "${LC_ALL:-${LANG:-}}" in ko*) echo ko ;; *) echo en ;; esac)}"
cd "$HERE/$DEMO_LANG" || { echo "no demo data for DEMO_LANG=$DEMO_LANG" >&2; exit 2; }
MODEL="${MODEL:-haiku}"
AUTO="${AUTO:-}"

if [ "$DEMO_LANG" = ko ]; then
  TITLES=("" "정상 작업은 그대로 통과" "프롬프트에 주민등록번호 → 모델 호출 전에 차단" "고객 명단 파일 읽기 → Read 도구 거부"
          "정규식으로는 못 잡는 민감 정보 (건강 정보 + 특정인) → decider 가 판단해 거부" "셸로 우회 시도 (cat) → 대상 파일을 검사해 거부")
  PROMPTS=("" "architecture.md 를 읽고 한 문장으로 요약해줘."
           "고객 주민등록번호 900101-1234567 로 가입 이력 조회하는 SQL 짜줘"
           "customers.csv 를 읽고 고객이 몇 명인지 알려줘. 도구가 차단되면 차단 메시지를 그대로 보여주고 우회하지 마."
           "support_ticket.txt 를 읽고 요약해줘. 도구가 차단되면 차단 메시지를 그대로 보여주고 우회하지 마."
           "Bash 로 'cat customers.csv' 를 실행해서 내용을 보여줘. 차단되면 차단 메시지를 그대로 보여주고 우회하지 마.")
  NEXT="(Enter)"
else
  TITLES=("" "Normal work passes through" "A national ID in the prompt -> blocked before the model is called"
          "Reading the customer list -> the Read tool is denied"
          "Sensitive data regex cannot catch (a named person's health) -> decider denies it"
          "Trying the shell instead (cat) -> the file is checked and denied")
  PROMPTS=("" "Read architecture.md and summarize it in one sentence."
           "Write SQL to look up the account history of the customer with resident number 900101-1234567"
           "Read customers.csv and tell me how many customers it lists. If a tool is blocked, quote the block message and do not work around it."
           "Read support_ticket.txt and summarize it. If a tool is blocked, quote the block message and do not work around it."
           "Run 'cat customers.csv' with Bash and show the output. If it is blocked, quote the block message and do not work around it.")
  NEXT="(Enter)"
fi
TOOLS=("" "Read" "" "Read" "Read" "Bash")

type_out() {
  local s="$1" i
  for ((i = 0; i < ${#s}; i++)); do printf '%s' "${s:i:1}"; sleep 0.025; done
  echo
}

next() {
  if [ -n "$AUTO" ]; then sleep "$AUTO"; else read -r -p $'\n\033[2m'"$NEXT"$'\033[0m ' _; fi
}

scene() {
  local n="$1" args=(-p "${PROMPTS[$1]}" --model "$MODEL" --max-turns 4)
  [ -n "${TOOLS[$n]}" ] && args+=(--allowedTools "${TOOLS[$n]}")
  [ -n "${SETTINGS:-}" ] && args+=(--settings "$SETTINGS")
  clear
  printf '\033[1;36m[%s/5] %s\033[0m\n\n' "$n" "${TITLES[$n]}"
  printf '\033[1;33m> \033[0m'
  type_out "${PROMPTS[$n]}"
  echo
  claude "${args[@]}" </dev/null
  next
}

SCENES=("$@")
[ ${#SCENES[@]} -eq 0 ] && SCENES=(1 2 3 4 5)
for n in "${SCENES[@]}"; do scene "$n"; done
