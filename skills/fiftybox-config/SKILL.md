---
name: fiftybox-config
description: fiftybox-execute/fiftybox-local이 쓰는 CLI provider(Pi, Codex, CommandCode, Grok, opencode)와 그 하위 모델의 사용 가능 여부를 체크박스 TUI로 켜고 끈다. 구독 상황이 바뀌었을 때, 또는 /fiftybox-config를 호출했을 때 사용한다.
---

# Fiftybox Config

`fiftybox-execute`/`fiftybox-local`이 어떤 CLI 도구·모델을 쓸 수 있는지는
`~/.claude/fiftybox-config.json`(머신 전역, 프로젝트 무관) 하나로 정해진다.
이 스킬은 그 파일을 사람이 직접 체크박스로 켜고 끄는 TUI만 제공한다 —
구독·로그인 상태를 대신 확인해주지는 않는다.

## 호출

`/fiftybox-config`를 부르면 Claude는 TUI를 대신 실행하지 않는다. curses TUI는
실제 키보드가 있는 사람 손에서만 동작하므로, 다음을 안내하고 멈춘다:

```
! python3 ~/.claude/skills/fiftybox-config/scripts/config_tui.py
```

사용자가 `!` 접두사로 직접 터미널에서 실행하게 한다.

## TUI 조작

- ↑/↓ (또는 k/j): 이동
- Space: 선택한 provider 또는 모델 체크박스 토글
- Enter: provider 행 펼치기/접기 (하위 모델 표시)
- `a`: 선택한 provider(또는 펼쳐진 Pi 백엔드의 모델 행)에 모델 추가
- `d`: 선택한 모델 행 삭제 (provider 행 자체는 삭제 불가)
- `s`: 저장하고 종료
- `q`: 저장하지 않고 종료

## 설정 파일

경로: `~/.claude/fiftybox-config.json`

```json
{
  "lane_priority": ["codex-write", "pi", "grok", "commandcode"],
  "providers": {
    "codex-write": {"enabled": true, "models": {"gpt-5.6-luna": true, "gpt-5.6-terra": false}},
    "pi": {"enabled": true, "backends": {
      "zai-coding": {"models": {"glm-5.3-flash": true}},
      "opencode-go": {"models": {"deepseek-v4-flash": true}},
      "modal-qwen38": {"models": {"qwen3.8-27b-q4_k_m": true}},
      "nvidia-nim": {"models": {
        "openai/gpt-oss-120b": true,
        "moonshotai/kimi-k3": true,
        "poolside/laguna-xs-2.1": true,
        "minimaxai/minimax-m3": true
      }},
      "openrouter-free": {"models": {
        "z-ai/glm-5.2:free": true,
        "poolside/laguna-s-2.1:free": true,
        "thinkingmachines/inkling:free": true,
        "thinkingmachines/inkling-small:free": true,
        "cohere/north-mini-code:free": true
      }}
    }},
    "grok": {"enabled": true, "models": {"grok-4.6": true}},
    "commandcode": {"enabled": true, "models": {"qwen/qwen3.7-flash": true, "zai-org/glm-5.2": true}},
    "opencode": {"enabled": true}
  }
}
```

`lane_priority`는 fiftybox-execute의 4단계 우선순위 자리를 어떤 provider가
기본으로 채우는지의 순서다. 이 스킬의 TUI로는 순서를 바꾸지 않는다 — 필요하면
파일을 직접 편집한다. provider가 `enabled: false`거나 켜진 모델이 하나도
없으면, fiftybox-execute의 lane allocator가 `lane_priority`의 다음 값으로
자동 대체한다.

파일이 없으면 TUI 최초 실행 시 리포 기본값으로 만든다. JSON이 깨져 있으면
`.bak`으로 백업하고 기본값으로 재생성한 뒤 화면에 경고를 보여준다.

## fiftybox-execute / fiftybox-local과의 관계

이 스킬은 설정을 저장하기만 한다. 실제로 이 설정을 읽어 preflight를
건너뛰거나 lane/후보 풀을 재배정하는 것은 `/fiftybox-execute`와
`/fiftybox-local` 쪽 책임이다.
